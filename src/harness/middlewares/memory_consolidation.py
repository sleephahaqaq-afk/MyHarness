"""情节归档（COLD 层写入口）。

拿到 ``thread_id`` 才归档：ID 缺失时跳过，避免所有会话写进同一个
``ep_unknown`` 互相覆盖（ERP 项目踩过的坑）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware

from ..log_utils import middleware_logger
from ..memory.config import DEFAULT_MEMORY_CONFIG
from ..memory.keeper import MemoryKeeper
from ..runtime_context import current_thread_id


def _last_ai_text(messages: list) -> str:
    for message in reversed(messages or []):
        if getattr(message, "type", "") == "ai":
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = " ".join(p for p in parts if p).strip()
                if text:
                    return text
    return ""


def _first_human_text(messages: list) -> str:
    for message in messages or []:
        if getattr(message, "type", "") == "human":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content.strip()
    return ""


class MemoryConsolidationMiddleware(AgentMiddleware):
    """after_agent 时把本轮对话归档成一条情节记忆。"""

    def __init__(
        self,
        keeper_factory: Optional[Callable[[], Optional[MemoryKeeper]]] = None,
        *,
        backend: Any = None,
        user_id: str = "default_user",
        config: Any = None,
        summarizer: Optional[Callable[[list], str]] = None,
    ) -> None:
        self._keeper_factory = keeper_factory
        self._backend = backend
        self._user_id = user_id
        self._config = config or DEFAULT_MEMORY_CONFIG
        self._summarizer = summarizer

    @property
    def name(self) -> str:
        return "MemoryConsolidationMiddleware"

    def _keeper(self) -> Optional[MemoryKeeper]:
        if self._keeper_factory is not None:
            return self._keeper_factory()
        if self._backend is None:
            return None
        return MemoryKeeper(self._backend, self._user_id, self._config)

    def after_agent(self, state: Any, runtime: Any) -> Optional[dict]:
        keeper = self._keeper()
        if keeper is None:
            return None
        try:
            thread_id = current_thread_id(runtime)
            if not thread_id:
                middleware_logger.warning("Skip episode archive: missing thread_id")
                return None

            messages = state.get("messages", []) if isinstance(state, dict) else []
            if not messages:
                return None

            if self._summarizer is not None:
                summary = self._summarizer(messages) or ""
            else:
                question = _first_human_text(messages)[:120]
                answer = _last_ai_text(messages)[: self._config.episode_summary_chars]
                summary = f"Q: {question} | A: {answer}" if question else answer
            if not summary:
                return None

            keeper.archive_episode(thread_id, summary, source={"thread_id": thread_id})
            middleware_logger.info(f"Episode archived for thread={thread_id}")
        except Exception as exc:
            middleware_logger.warning(f"Failed to archive episode: {exc}")
        return None

    async def aafter_agent(self, state: Any, runtime: Any) -> Optional[dict]:
        return await asyncio.to_thread(self.after_agent, state, runtime)
