"""记忆打分：文本相关度 + 时间衰减 + 引用频次 + 置信度。

文本侧同时处理中英文：英文按词切分，中文按字符 bigram 切分，
避免"中文整句无法被空白切分"导致相关度恒为 0。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Iterable, Set

from .types import MemoryItem, _parse_iso

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    lowered = text.lower()
    tokens = set(_TOKEN_RE.findall(lowered))
    # 中文：字符 bigram，兼顾单字查询
    han = re.findall(r"[\u4e00-\u9fff]", lowered)
    tokens.update(han)
    tokens.update(a + b for a, b in zip(han, han[1:]))
    return tokens


def text_similarity(query: str, item: MemoryItem) -> float:
    """查询与记忆文本的相关度（0~1，覆盖率而非绝对重合度）。"""
    q = tokenize(query)
    if not q:
        return 0.0
    d = tokenize(item.searchable_text())
    if not d:
        return 0.0
    hit = len(q & d)
    return hit / len(q)


def recency_score(item: MemoryItem, half_life_days: float, now: datetime | None = None) -> float:
    """半衰期指数衰减，越新越接近 1。"""
    if half_life_days <= 0:
        return 1.0
    created = _parse_iso(item.created_at)
    if created is None:
        return 0.5
    age = max(0.0, ((now or datetime.now()) - created).total_seconds() / 86400.0)
    return math.pow(0.5, age / half_life_days)


def access_score(item: MemoryItem) -> float:
    """引用频次取对数饱和，避免高频记忆长期霸榜。"""
    if item.access_count <= 0:
        return 0.0
    return min(1.0, math.log1p(item.access_count) / math.log1p(20))


def score_item(query: str, item: MemoryItem, config, now: datetime | None = None) -> float:
    """加权总分 = 文本 + 新鲜度 + 频次 + 置信度。"""
    text = text_similarity(query, item)
    if text <= 0:
        return 0.0
    return (
        config.weight_text * text
        + config.weight_recency * recency_score(item, config.half_life_days, now)
        + config.weight_access * access_score(item)
        + config.weight_confidence * max(0.0, min(1.0, item.confidence))
    )


def rank(query: str, items: Iterable[MemoryItem], config, k: int, now: datetime | None = None):
    """按总分降序返回前 k 条（低于 min_retrieval_score 视为噪声丢弃）。"""
    scored = []
    for item in items:
        value = score_item(query, item, config, now)
        if value >= config.min_retrieval_score:
            scored.append((value, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:k]]
