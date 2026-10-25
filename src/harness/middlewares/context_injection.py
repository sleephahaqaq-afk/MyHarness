"""用户上下文注入（请求级隔离）。

用 ``thread_id → HarnessContext`` 的字典保存，避免全局单例在不同会话间串扰；
``update_context`` 支持在 Agent 复用期间动态替换上下文。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from ..log_utils import middleware_logger
from ..runtime_context import current_thread_id
from ..schema import HarnessContext

CONTEXT_SLOT = "<!-- LIVE_USER_CONTEXT -->"


class ContextInjectionMiddleware(AgentMiddleware):
    """把用户身份与静态偏好注入系统提示词。"""

    def __init__(self, user_context: Optional[HarnessContext] = None) -> None:
        self._default_context = user_context or HarnessContext()
        self._contexts: Dict[str, HarnessContext] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "ContextInjectionMiddleware"

    def update_context(self, context: HarnessContext, thread_id: str = "") -> None:
        with self._lock:
            self._contexts[thread_id] = context

    def _context_for(self, thread_id: str) -> HarnessContext:
        with self._lock:
            return self._contexts.get(thread_id, self._default_context)

    def _inject(self, request: Any) -> Any:
        thread_id = current_thread_id(getattr(request, "runtime", None))
        ctx = self._context_for(thread_id)
        block = f"当前用户：{ctx.username}（id={ctx.user_id}）"
        if ctx.preferences:
            prefs = "；".join(f"{k}={v}" for k, v in list(ctx.preferences.items())[:12])
            block += f"\n已登记偏好：{prefs}"

        blocks = list(request.system_message.content_blocks) if request.system_message else []
        found = False
        for i, item in enumerate(blocks):
            if item.get("type") == "text" and CONTEXT_SLOT in item.get("text", ""):
                blocks[i] = {**item, "text": item["text"].replace(CONTEXT_SLOT, block)}
                found = True
        if not found:
            blocks.append({"type": "text", "text": block})
        return request.override(system_message=SystemMessage(content=blocks))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._inject(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._inject(request))

    async def abefore_agent(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.before_agent, state, runtime)

    def before_agent(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        thread_id = current_thread_id(runtime)
        middleware_logger.debug(
            f"Context injected: thread={thread_id or '-'}, "
            f"user={self._context_for(thread_id).user_id}"
        )
        return None
