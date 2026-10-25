"""离线演示模型：没有真实 LLM_API_KEY 时，用 ``--demo`` 把整条链路跑通。

定位：**只属于 scripts/**，不进 ``src/harness``。基座代码不认这个模型，
必须由 `serve.py --demo` 显式注入，不存在任何隐式回退。

它能演示的链路：

    HTTP/SSE 分帧 → EventBridge 翻译 → 中间件栈 → 阶段推进 → 记忆落库

不能演示的：真实模型能力、真实工具调用（联网工具会真的发请求，这里不触发）。
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

REPLY_DEFAULT = """## 演示模式回复

这是脚本化模型的固定回答，用来验证 **前端 ↔ SSE ↔ 基座** 的接线，不是真实模型输出。

### 这一轮实际发生了什么

1. `POST /api/chat` 返回 `text/event-stream`
2. `EventBridge` 把 `on_chat_model_stream` 翻成 `delta`，逐块推给前端
3. 中间件栈顺序执行：阶段推进 → 上下文注入 → WARM 记忆 → 技能目录 → 记忆抽取 → 情节归档 → 工具结果截断
4. 结束后 `after_agent` 把本轮偏好写进记忆后端

### 想验证记忆？

换成：**以后都用中文、表格输出** —— 再刷新右侧记忆面板，会看到 `output_format` / `language` 两条。
"""

REPLY_NEWS = """## AI 信息速览（演示数据）

> 以下条目是脚本化模型的占位内容，**不是真实抓取结果**。

### top_items

| # | 主题 | 一句话 |
|---|------|--------|
| 1 | 长上下文推理 | 稀疏注意力把有效上下文推到百万级 |
| 2 | Agent 工程化 | 关注点从「能不能调工具」转向「可观测与可回滚」 |
| 3 | 端侧小模型 | 量化 + 蒸馏让 7B 以下模型承担更多本地任务 |

### 接入真实数据

要拿到真东西，把 `.env` 里的 `LLM_API_KEY` 换成真实密钥，然后：

```bash
python scripts/serve.py          # 去掉 --demo
```

这时主 Agent 会通过 `task` 工具委派给 `ai-news-scout` 子 Agent，
它的 `web_search` / `web_fetch` 才会真的出网。
"""

REPLY_MEMORY = """## 记忆面板怎么看

左侧对话里说过的偏好会在这一轮结束后落到后端：

- **WARM**：每轮模型调用都注入，适合「输出格式 / 语言 / 详略」这类稳定偏好
- **COLD**：不主动注入，靠 `read_memory` 检索，适合情节与历史结论
- **HOT**：LangGraph checkpointer 里的会话本身，不占记忆容量

`GET /api/memory?user_id=demo` 能直接看到当前落库结果。
"""


def _split(text: str, size: int = 12) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _flatten(messages: Any) -> str:
    parts: List[str] = []
    for message in messages or []:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return "\n".join(parts)


def _last_human(messages: Any) -> str:
    """只取最后一条人类消息——扫全量会把系统提示词里的词也命中。"""
    for message in reversed(list(messages or [])):
        if getattr(message, "type", "") == "human":
            return _flatten([message])
    return _flatten(messages)


class DemoChatModel(BaseChatModel):
    """按关键词挑一段固定回答，并模拟逐块流式输出。"""

    model_name: str = "harness-demo"
    chunk_size: int = 12
    chunk_delay: float = 0.02  # 让前端能看清逐字效果，仅演示用

    @property
    def _llm_type(self) -> str:
        return "harness-demo"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "DemoChatModel":
        # 演示模式不真的调工具，但 import 时 deepagents 会 bind_tools
        return self

    def _reply(self, messages: Any) -> str:
        text = _last_human(messages)
        lowered = text.lower()
        if "新闻" in text or "最新" in text or "资讯" in text or "news" in lowered:
            return REPLY_NEWS
        if "记忆" in text or "memory" in lowered:
            return REPLY_MEMORY
        return REPLY_DEFAULT

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._reply(messages)))])

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        for piece in _split(self._reply(messages), self.chunk_size):
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
