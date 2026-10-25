"""超长工具输出截断。

工具返回动辄几万字符会把上下文撑爆。这里只做**可见的截断**（附提示），
不做摘要改写——截断是保守的、可预期的，摘要则可能引入幻觉。
"""
from __future__ import annotations

from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from ..log_utils import middleware_logger

TRUNCATION_NOTICE = "\n...[输出已截断，完整结果请缩小查询范围或再次调用]"


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + TRUNCATION_NOTICE


class ToolsSummarizationMiddleware(AgentMiddleware):
    """限制单条工具结果进入上下文的字符数。"""

    def __init__(self, max_chars: int = 8000) -> None:
        self.max_chars = max_chars

    @property
    def name(self) -> str:
        return "ToolsSummarizationMiddleware"

    def _maybe_truncate(self, result: Any) -> Any:
        content = getattr(result, "content", None)
        if not isinstance(content, str) or len(content) <= self.max_chars:
            return result

        middleware_logger.info(
            f"Truncated tool output: {len(content)} -> {self.max_chars} chars"
        )
        shortened = truncate(content, self.max_chars)
        try:
            return result.model_copy(update={"content": shortened})
        except Exception:  # 非 pydantic 结果：退化成最小 ToolMessage
            return ToolMessage(
                content=shortened, tool_call_id=getattr(result, "tool_call_id", "")
            )

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._maybe_truncate(handler(request))

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._maybe_truncate(await handler(request))
