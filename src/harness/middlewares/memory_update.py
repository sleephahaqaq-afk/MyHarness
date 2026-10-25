"""偏好自动提取（WARM 层写入口）。

只消费**最近一轮**用户消息：从 checkpoint 恢复的会话里，早期轮次的偏好
不该被反复重放，否则旧说法会覆盖新说法。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware

from ..log_utils import middleware_logger
from ..memory.config import DEFAULT_MEMORY_CONFIG
from ..memory.extractor import extract_preferences
from ..memory.keeper import MemoryKeeper
from ..runtime_context import current_thread_id


class MemoryUpdateMiddleware(AgentMiddleware):
    """after_agent 时把本轮偏好合并进记忆。"""

    def __init__(
        self,
        keeper_factory: Optional[Callable[[], Optional[MemoryKeeper]]] = None,
        *,
        backend: Any = None,
        user_id: str = "default_user",
        config: Any = None,
        llm_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._keeper_factory = keeper_factory
        self._backend = backend
        self._user_id = user_id
        self._config = config or DEFAULT_MEMORY_CONFIG
        self._llm_factory = llm_factory
        self._migrated = False

    @property
    def name(self) -> str:
        return "MemoryUpdateMiddleware"

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
            if not self._migrated:
                self._migrated = True
                keeper.migrate_legacy_preferences()

            messages = state.get("messages", []) if isinstance(state, dict) else []
            if not messages:
                return None

            start = next(
                (
                    i
                    for i in range(len(messages) - 1, -1, -1)
                    if getattr(messages[i], "type", "") == "human"
                ),
                len(messages),
            )
            current = messages[start:]
            updates = extract_preferences(current, self._config)
            if not updates:
                return None

            keeper.merge_preferences(updates, source={"thread_id": current_thread_id(runtime)})
            middleware_logger.info(f"User preferences merged: {sorted(updates)}")
        except Exception as exc:  # 记忆出错绝不能打断对话
            middleware_logger.warning(f"Failed to update user preferences: {exc}")
        return None

    async def aafter_agent(self, state: Any, runtime: Any) -> Optional[dict]:
        # 记忆 IO 是同步的，放到线程里跑，避免阻塞事件循环
        return await asyncio.to_thread(self.after_agent, state, runtime)
