"""三层记忆配置。

只依赖标准库，便于在不装 langchain 的环境里单跑记忆单测。
所有阈值可用环境变量覆盖，默认值按"单机 + 少量用户"规模给出。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from ..env_utils import env_bool, env_float, env_int
except ImportError:  # pragma: no cover - 作为独立模块被引用时
    import os

    def env_int(name: str, default: int) -> int:
        return int(os.getenv(name, default))

    def env_float(name: str, default: float) -> float:
        return float(os.getenv(name, default))

    def env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class MemoryConfig:
    # --- 分层 ---
    warm_episode_days: int = 7          # 情节记忆停留 WARM 的天数
    retrieval_k: int = 5                # COLD 单次检索返回条数
    min_retrieval_score: float = 0.08   # COLD 检索最低相关度

    # --- 生命周期 ---
    episode_ttl_days: int = 90
    semantic_ttl_days: Optional[int] = None
    procedural_ttl_days: Optional[int] = None
    max_episodes: int = 200             # 每用户最多情节条数，超出淘汰最旧
    max_semantic_history: int = 3       # 同一 key 最多保留几条历史版本

    # --- 打分 ---
    half_life_days: float = 30.0
    weight_text: float = 0.6
    weight_recency: float = 0.2
    weight_access: float = 0.1
    weight_confidence: float = 0.1

    # --- 整合 / 注入 ---
    warm_brief_chars: int = 4000        # 注入系统提示词的总字符上限
    warm_item_chars: int = 160          # 单条摘要长度
    max_warm_episodes: int = 5
    episode_summary_chars: int = 400

    # --- 治理 ---
    immutable_confidence: float = 1.0     # >= 该置信度的事实不会被更低置信度覆盖

    # --- 提取 / 工具 ---
    llm_extraction_enabled: bool = False
    memory_tools_enabled: bool = True

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        return cls(
            warm_episode_days=env_int("MEMORY_WARM_EPISODE_DAYS", 7),
            retrieval_k=env_int("MEMORY_RETRIEVAL_K", 5),
            min_retrieval_score=env_float("MEMORY_MIN_RETRIEVAL_SCORE", 0.08),
            episode_ttl_days=env_int("MEMORY_EPISODE_TTL_DAYS", 90),
            semantic_ttl_days=env_int("MEMORY_SEMANTIC_TTL_DAYS", 0) or None,
            procedural_ttl_days=env_int("MEMORY_PROCEDURAL_TTL_DAYS", 0) or None,
            max_episodes=env_int("MEMORY_MAX_EPISODES", 200),
            max_semantic_history=env_int("MEMORY_MAX_SEMANTIC_HISTORY", 3),
            half_life_days=env_float("MEMORY_HALF_LIFE_DAYS", 30.0),
            warm_brief_chars=env_int("MEMORY_WARM_BRIEF_CHARS", 4000),
            warm_item_chars=env_int("MEMORY_WARM_ITEM_CHARS", 160),
            max_warm_episodes=env_int("MEMORY_MAX_WARM_EPISODES", 5),
            episode_summary_chars=env_int("MEMORY_EPISODE_SUMMARY_CHARS", 400),
            immutable_confidence=env_float("MEMORY_IMMUTABLE_CONFIDENCE", 1.0),
            llm_extraction_enabled=env_bool("MEMORY_LLM_EXTRACTION", False),
            memory_tools_enabled=env_bool("MEMORY_TOOLS_ENABLED", True),
        )


DEFAULT_MEMORY_CONFIG = MemoryConfig.from_env()
