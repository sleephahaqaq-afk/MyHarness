"""离线测试用脚本化模型。

deepagents 会给模型 bind_tools，而 langchain-core 自带的 fake model 不支持，
所以这里给一个最小实现：按队列返回预设消息，并记录收到的系统提示词。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, ClassVar, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


def _split(text: str, size: int = 8) -> List[str]:
    """把回复切成小块，模拟逐字返回。空串返回空列表。"""
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _reply_chunks(message: Any) -> List[AIMessageChunk]:
    """把一条完整 AIMessage 拆成流式 chunk。

    纯文本按块切；带工具调用的回复额外补一个只含 tool_call_chunks 的尾部 chunk，
    否则流式路径会把工具调用吃掉。
    """
    content = getattr(message, "content", "")
    chunks = [AIMessageChunk(content=piece) for piece in _split(content if isinstance(content, str) else "")]

    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        chunks.append(
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": call.get("name"),
                        "args": json.dumps(call.get("args") or {}, ensure_ascii=False),
                        "id": call.get("id") or f"call_{index}",
                        "index": index,
                    }
                    for index, call in enumerate(tool_calls)
                ],
            )
        )
    if not chunks:
        chunks.append(AIMessageChunk(content=""))
    return chunks


class ScriptedChatModel(BaseChatModel):
    """按队列返回消息；队列空了返回固定的兜底 AIMessage。"""

    queue: List[Any] = Field(default_factory=list)
    model_name: str = "scripted"
    bound_tools: Optional[List[Any]] = None
    call_count: int = 0

    # 类级记录：bind_tools 会 model_copy，实例字段无法跨副本累积
    log: ClassVar[List[str]] = []
    tool_names: ClassVar[List[str]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        ScriptedChatModel.tool_names = [getattr(t, "name", str(t)) for t in tools or []]
        return self.model_copy(update={"bound_tools": list(tools or [])})  # type: ignore[return-value]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        texts: List[str] = []
        for message in messages or []:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if getattr(message, "type", "") == "system":
                ScriptedChatModel.log.append("\n".join(texts))
                texts = []

        self.call_count += 1
        if self.queue:
            reply = self.queue.pop(0)
        else:
            reply = AIMessage(content="（脚本响应已用尽）")
        return ChatResult(generations=[ChatGeneration(message=reply)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        """异步路径：SSE / astream_events 会走这里。"""
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        """真流式。

        langchain-core 的 `_should_stream()` 只有在 `_stream` / `_astream` 至少实现
        一个时才走流式分支，否则直接 `_agenerate` 一把梭，`on_chat_model_stream`
        一个事件都不会有。所以这里必须实现，否则 SSE 链路测不出流式行为。

        `on_llm_new_token` 由基类在 `_agenerate_with_cache` 里统一调用，这里只管 yield。
        """
        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for chunk in _reply_chunks(result.generations[0].message):
            yield ChatGenerationChunk(message=chunk)
