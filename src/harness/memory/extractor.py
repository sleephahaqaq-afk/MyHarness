"""从对话里抽取可长期保存的偏好（确定性规则，零额外成本）。

规则层只做"高置信的显式表达"：祈使句 + 稳定意图（以后/默认/总是）。
临时表达（"这次…"、"先…"）和否定表达（"不要/别/不用"）一律跳过，
避免一次性的说法被当成长期偏好反复写回。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 临时表达：命中即跳过整条抽取
TEMPORARY_MARKERS = ("这次", "这回", "本次", "先这样", "临时", "暂时", "就这一次")
# 否定表达：命中即认为是在**取消**某种偏好
NEGATION_MARKERS = ("不要", "别", "不用", "不需要", "取消", "以后别", "不再")

OUTPUT_KEYWORDS = {
    "markdown": "markdown",
    "md": "markdown",
    "表格": "table",
    "table": "table",
    "csv": "csv",
    "json": "json",
    "html": "html",
}

LANGUAGE_KEYWORDS = {
    "中文": "zh",
    "英文": "en",
    "english": "en",
    "双语": "bilingual",
}

VERBOSITY_KEYWORDS = {
    "简洁": "concise",
    "简明": "concise",
    "简短": "concise",
    "详细": "detailed",
    "展开": "detailed",
    "深入": "detailed",
}

CHART_KEYWORDS = {
    "柱状图": "bar",
    "柱状": "bar",
    "bar": "bar",
    "折线": "line",
    "line": "line",
    "饼图": "pie",
    "pie": "pie",
    "雷达": "radar",
    "radar": "radar",
    "散点": "scatter",
    "scatter": "scatter",
}

# key -> (同义词表, 规范值)
DIMENSIONS = {
    "output_format": OUTPUT_KEYWORDS,
    "language": LANGUAGE_KEYWORDS,
    "verbosity": VERBOSITY_KEYWORDS,
    "chart_type": CHART_KEYWORDS,
}


def _text_of(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def _is_temporary(text: str) -> bool:
    return any(marker in text for marker in TEMPORARY_MARKERS)


def _is_negated(text: str, hit_index: int) -> bool:
    """关键词前一小段窗口内是否出现否定词。"""
    window = text[max(0, hit_index - 12) : hit_index]
    return any(marker in window for marker in NEGATION_MARKERS)


def extract_preferences(messages: Optional[List[Any]], config: Any = None) -> Dict[str, str]:
    """从消息里抽取偏好字典；抽不到返回空 dict。"""
    updates: Dict[str, str] = {}
    if not messages:
        return updates

    for message in messages:
        if getattr(message, "type", "") != "human":
            continue
        text = _text_of(message)
        if not text or _is_temporary(text):
            continue
        lowered = text.lower()
        for key, synonyms in DIMENSIONS.items():
            for word, value in synonyms.items():
                index = lowered.find(word.lower())
                if index < 0:
                    continue
                if _is_negated(text, index):
                    continue
                updates[key] = value
                break
    return updates


def llm_extract_preferences(messages: List[Any], model: Any) -> Dict[str, str]:
    """可选的 LLM 抽取（默认关闭，失败由调用方降级到规则）。"""
    raise NotImplementedError(
        "LLM 抽取需在业务层注入 model 与 prompt；基座默认走规则抽取（零成本、可复现）。"
    )


__all__ = ["extract_preferences", "llm_extract_preferences", "DIMENSIONS"]
