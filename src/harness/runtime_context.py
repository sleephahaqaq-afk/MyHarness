"""从 LangGraph Runtime 里拿运行期标识。

``thread_id`` 是跨会话记忆的归档键：拿不到就返回空串，调用方必须跳过归档，
绝不能退化成 ``ep_unknown`` 让所有会话互相覆盖。
"""
from __future__ import annotations

from typing import Any, Optional


def _walk(obj: Any, key: str, depth: int = 4) -> Optional[Any]:
    """在 dict / 对象属性里按 key 逐层查找（兼容 dict 形态的 runtime）。"""
    if depth <= 0 or obj is None:
        return None
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            return obj[key]
        for value in obj.values():
            found = _walk(value, key, depth - 1)
            if found is not None:
                return found
        return None
    for attr in ("configurable", "config", "context", "metadata"):
        found = _walk(getattr(obj, attr, None), key, depth - 1)
        if found is not None:
            return found
    return getattr(obj, key, None)


def _from_langgraph_config() -> str:
    """从 langgraph 的 contextvar 里取 thread_id（同步/异步均可用）。"""
    try:
        from langgraph.config import get_config

        configurable = (get_config() or {}).get("configurable") or {}
        return str(configurable.get("thread_id") or "")
    except Exception:
        return ""


def current_thread_id(runtime: Any) -> str:
    """按优先级取 thread_id：Runtime.execution_info → 结构遍历 → langgraph config。"""
    # langgraph 1.x 的 Runtime 把会话信息放在 execution_info 上
    value = getattr(getattr(runtime, "execution_info", None), "thread_id", None)
    if value:
        return str(value)

    value = _walk(runtime, "thread_id")
    if value:
        return str(value)

    return _from_langgraph_config()


def current_user_id(runtime: Any, default: str = "default_user") -> str:
    value = _walk(runtime, "user_id")
    return str(value) if value else default
