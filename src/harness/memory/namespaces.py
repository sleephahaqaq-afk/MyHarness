"""记忆命名空间规范。

    ("memories", <user_id>, "semantic")    用户级稳定事实（偏好、画像）
    ("memories", <user_id>, "episodic")    用户级情节归档（做过什么）
    ("memories", <user_id>, "procedural")  用户级经验 / 流程（怎么做事）
    ("memories", "org", "policies")        组织级只读策略

``("user-preferences", <user_id>)`` 是 WARM 层的投影/缓存（只放偏好字典），
由 MemoryKeeper 单向同步，不反向写回——真正的本体在 ``memories`` 下。
"""
from __future__ import annotations

from typing import Optional, Tuple

ROOT = "memories"

SEMANTIC = "semantic"
EPISODIC = "episodic"
PROCEDURAL = "procedural"
POLICIES = "policies"

ORG_ID = "org"

LEGACY_PREFERENCES_ROOT = "user-preferences"
LEGACY_PREFERENCES_KEY = "preferences"


def semantic_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", SEMANTIC)


def episodic_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", EPISODIC)


def procedural_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", PROCEDURAL)


def org_policies_ns() -> Tuple[str, str, str]:
    return (ROOT, ORG_ID, POLICIES)


def legacy_preferences_ns(user_id: str) -> Tuple[str, str]:
    return (LEGACY_PREFERENCES_ROOT, user_id or "default_user")


def type_ns(user_id: str, memory_type: str) -> Tuple[str, str, str]:
    if memory_type == EPISODIC:
        return episodic_ns(user_id)
    if memory_type == PROCEDURAL:
        return procedural_ns(user_id)
    return semantic_ns(user_id)


def user_namespaces(user_id: str) -> Tuple[Tuple[str, str, str], ...]:
    return (semantic_ns(user_id), episodic_ns(user_id), procedural_ns(user_id))


def user_of(namespace) -> Optional[str]:
    """命名空间归属的用户；组织级或非法命名空间返回 None。"""
    parts = tuple(str(p) for p in (namespace or ()))
    if len(parts) < 2 or parts[0] != ROOT:
        return None
    if parts[1] == ORG_ID:
        return None
    return parts[1] or None
