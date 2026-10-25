"""暴露给 Agent 的记忆工具（COLD 检索 + 显式写入）。

用工厂函数而不是模块级工具：工具需要绑定当前用户的 MemoryKeeper，
而 keeper 依赖请求级 user_id，不能做成全局单例。
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from langchain_core.tools import tool

from ..log_utils import memory_logger
from .keeper import MemoryKeeper
from .types import EPISODIC, PROCEDURAL, SEMANTIC


def make_memory_tools(
    keeper_factory: Callable[[], Optional[MemoryKeeper]], config: Any
) -> List[Any]:
    """生成 read_memory / remember 两个工具。

    Args:
        keeper_factory: 每次调用返回当前用户的 MemoryKeeper（可为 None）。
        config: MemoryConfig，用于判断是否启用与检索条数。
    """

    @tool
    def read_memory(query: str, k: int = 5) -> str:
        """按需检索长期记忆（情节、经验、历史偏好）。不确定用户以前说过什么时调用。"""
        keeper = keeper_factory()
        if keeper is None:
            return "（记忆不可用：未配置存储后端）"
        try:
            hits = keeper.retrieve(query, k or config.retrieval_k)
        except Exception as exc:  # 记忆故障不能打断对话
            memory_logger.warning(f"read_memory failed: {exc}")
            return "（记忆检索暂不可用）"
        if not hits:
            return "（没有相关记忆）"
        lines = []
        for item in hits:
            stamp = item.created_at[:10]
            marker = "已失效" if item.is_invalidated() else item.type
            lines.append(f"- [{stamp}][{marker}] {item.summary or item.content[:160]}")
        return "\n".join(lines)

    @tool
    def remember(content: str, memory_type: str = "semantic", key: str = "") -> str:
        """显式记住一条信息。type 可选 semantic（稳定事实）/ episodic / procedural。"""
        keeper = keeper_factory()
        if keeper is None:
            return "（记忆不可用：未配置存储后端）"
        mtype = (memory_type or SEMANTIC).strip().lower()
        try:
            if mtype == EPISODIC:
                if not key:
                    return "（episodic 记忆必须用 key 传 thread_id，否则会互相覆盖）"
                item = keeper.archive_episode(
                    thread_id=key, summary=content[: config.episode_summary_chars], content=content
                )
            elif mtype == PROCEDURAL:
                item = keeper.write_procedural(content)
            else:
                if not key:
                    return "（semantic 记忆必须提供 key，便于后续冲突判定）"
                item = keeper.write_semantic(key, content, confidence=0.8, evidence="remember tool")
        except Exception as exc:
            memory_logger.warning(f"remember failed: {exc}")
            return "（写入失败）"
        if item is None:
            return "（未写入：可能被更高置信度的事实挡下）"
        return f"已记住：{item.id}"

    return [read_memory, remember]
