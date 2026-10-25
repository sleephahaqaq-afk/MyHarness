"""把 LangGraph 的流式事件翻译成前端 EngineEvent。

映射规则（astream_events v2）：

    on_chat_model_start   → assistant_start（多轮模型调用 = 多条 assistant 消息）
    on_chat_model_stream  → delta
    on_chat_model_end     → delta 兜底（模型不支持流式时整轮只有一个 end 事件）
    on_tool_start (task)  → delegate_start
    on_tool_start (其他)  → tool_start
    on_tool_end           → tool_end / delegate_end
    on_chain_end *.after_model → phase（阶段推进由 HarnessPhaseMiddleware 写在 state 里）

关于 `on_chat_model_end` 兜底：langchain-core 的 `_should_stream()` 在模型没有实现
`_stream` / `_astream` 时返回 False，此时整轮只会有一个 `on_chat_model_end`，正文
在 `data.output` 里。没有兜底的话前端会渲染出一个空气泡。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from ..log_utils import agent_logger


def sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def text_of(payload: Any) -> str:
    """从流式 chunk 或完整消息里取纯文本（忽略工具调用参数等块）。"""
    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _short(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else getattr(value, "content", None)
    if text is None:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    text = str(text)
    return text[:limit] + ("…" if len(text) > limit else "")


def _args_of(data: Dict[str, Any]) -> str:
    raw = data.get("input")
    if isinstance(raw, dict):
        return ", ".join(f"{k}={_short(v, 60)}" for k, v in list(raw.items())[:3])
    return _short(raw, 120)


class EventBridge:
    """一次对话的事件桥。持有当前消息 id 与工具调用映射。"""

    def __init__(self, user_id: str, session_id: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.message_id: Optional[str] = None
        self.tools: Dict[str, Dict[str, Any]] = {}  # run_id -> 前端 tool 信息
        self._streamed = False  # 当前 assistant 消息是否已发过 delta

    def _open_message(self) -> str:
        self.message_id = f"msg-{uuid.uuid4().hex[:10]}"
        self._streamed = False
        return self.message_id

    async def translate(self, agent: Any, message: str) -> AsyncIterator[str]:
        config = {"configurable": {"thread_id": self.session_id, "user_id": self.user_id}}

        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            name = str(event.get("name") or "")
            data = event.get("data") or {}

            if kind == "on_chat_model_start":
                # 上一段输出结束，开新消息
                if self.message_id:
                    yield sse({"type": "assistant_end", "id": self.message_id})
                yield sse({"type": "assistant_start", "id": self._open_message()})

            elif kind == "on_chat_model_stream":
                text = text_of(data.get("chunk"))
                if text and self.message_id:
                    self._streamed = True
                    yield sse({"type": "delta", "id": self.message_id, "text": text})

            elif kind == "on_chat_model_end":
                # 模型不支持流式（或本轮到不了流式分支）时，整轮只有这一个事件
                if self._streamed:
                    continue
                text = text_of(data.get("output"))
                if text and self.message_id:
                    self._streamed = True
                    yield sse({"type": "delta", "id": self.message_id, "text": text})

            elif kind == "on_tool_start":
                run_id = str(event.get("run_id") or uuid.uuid4().hex)
                raw_input = data.get("input")
                is_delegate = name == "task"
                if is_delegate:
                    payload = raw_input if isinstance(raw_input, dict) else {}
                    delegate_id = f"dlg-{run_id[:8]}"
                    self.tools[run_id] = {"kind": "delegate", "id": delegate_id}
                    yield sse(
                        {
                            "type": "delegate_start",
                            "messageId": self.message_id,
                            "delegate": {
                                "id": delegate_id,
                                "agent": str(payload.get("subagent_type") or "subagent"),
                                "task": str(payload.get("description") or "")[:200],
                                "tools": [],
                                "status": "running",
                            },
                        }
                    )
                else:
                    tool_id = f"tool-{run_id[:8]}"
                    self.tools[run_id] = {"kind": "tool", "id": tool_id}
                    yield sse(
                        {
                            "type": "tool_start",
                            "messageId": self.message_id,
                            "tool": {
                                "id": tool_id,
                                "name": name,
                                "args": _args_of(data),
                                "status": "running",
                            },
                        }
                    )

            elif kind == "on_tool_end":
                run_id = str(event.get("run_id") or "")
                record = self.tools.pop(run_id, None)
                if not record:
                    continue
                result = _short(data.get("output"))
                if record["kind"] == "delegate":
                    yield sse(
                        {
                            "type": "delegate_end",
                            "messageId": self.message_id,
                            "delegateId": record["id"],
                        }
                    )
                else:
                    yield sse(
                        {
                            "type": "tool_end",
                            "messageId": self.message_id,
                            "toolId": record["id"],
                            "result": result,
                            "durationMs": 0,
                        }
                    )

            elif kind == "on_chain_end" and name.endswith("after_model"):
                output = data.get("output")
                if isinstance(output, dict) and output.get("phase"):
                    yield sse({"type": "phase", "phase": output["phase"]})

        if self.message_id:
            yield sse({"type": "assistant_end", "id": self.message_id})
        yield sse({"type": "done"})

    async def error(self, message: str) -> AsyncIterator[str]:
        """错误用 system 事件回传，前端渲染成独立错误卡，不污染助手正文。"""
        yield sse({"type": "system", "text": message})
        yield sse({"type": "done"})
