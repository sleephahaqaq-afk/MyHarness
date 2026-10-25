"""基座状态与上下文定义。

- :class:`Phase`：Harness 四阶段（Planning → Executing → Review → Result）；
- :class:`HarnessContext`：随请求携带的用户上下文；
- :class:`HarnessState`：挂在 LangGraph AgentState 上的基座私有状态。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

try:  # langchain 未安装时（纯记忆单测）退化为普通 dict 标注
    from langchain.agents.middleware.types import AgentState
except Exception:  # pragma: no cover

    class AgentState(dict):  # type: ignore[no-redef]
        pass


class Phase(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    RESULT = "result"


PHASE_ORDER = (Phase.PLANNING, Phase.EXECUTING, Phase.REVIEWING, Phase.RESULT)


@dataclass
class HarnessContext:
    """一次请求的用户上下文。"""

    user_id: str = "default_user"
    username: str = "用户"
    preferences: Dict[str, Any] = field(default_factory=dict)
    warm_memory: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class HarnessState(AgentState):
    """基座在 AgentState 上扩展的字段。"""

    phase: str
    plan: list
    review: dict


def next_phase(phase: str | Phase) -> Phase:
    """返回下一阶段；已是最后阶段则停留在 RESULT。"""
    current = Phase(phase) if isinstance(phase, str) else phase
    index = PHASE_ORDER.index(current)
    return PHASE_ORDER[min(index + 1, len(PHASE_ORDER) - 1)]


__all__ = ["Phase", "PHASE_ORDER", "HarnessContext", "HarnessState", "next_phase"]
