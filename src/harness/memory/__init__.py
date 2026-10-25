"""三层记忆（HOT / WARM / COLD）。

- HOT：会话内状态与 checkpoint，由 LangGraph 持有，本模块不落盘；
- WARM：每次模型调用前注入系统提示词的偏好 + 近期情节摘要；
- COLD：按需检索的长期记忆（情节、程序记忆、失效历史）。

对外入口是 :class:`harness.memory.keeper.MemoryKeeper`，存储后端由
:mod:`harness.memory.store` 提供抽象，可替换成任意持久化实现。
"""

from .types import MemoryItem, SEMANTIC, EPISODIC, PROCEDURAL, HOT, WARM, COLD
from .config import MemoryConfig, DEFAULT_MEMORY_CONFIG
from .store import MemoryBackend, InMemoryBackend, FileBackend, MemoryRecord
from .keeper import MemoryKeeper

__all__ = [
    "MemoryItem",
    "MemoryConfig",
    "DEFAULT_MEMORY_CONFIG",
    "MemoryBackend",
    "InMemoryBackend",
    "FileBackend",
    "MemoryRecord",
    "MemoryKeeper",
    "SEMANTIC",
    "EPISODIC",
    "PROCEDURAL",
    "HOT",
    "WARM",
    "COLD",
]
