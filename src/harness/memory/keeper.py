"""跨会话记忆的统一治理入口。

职责边界：
- 写入：语义（偏好/事实）、情节（做过什么）、程序（怎么做事）；
- 冲突：同一逻辑 key 的新值让旧值失效（保留有限历史版本），
  但高置信度事实不会被更低置信度的事实覆盖；
- 遗忘：TTL 过期 + 数量淘汰；
- 读取：WARM 摘要（注入提示词）与 COLD 检索（按需）。

统一入口不等于数据库事务，也不提供分布式并发保证。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import MemoryConfig, DEFAULT_MEMORY_CONFIG
from .namespaces import (
    LEGACY_PREFERENCES_KEY,
    episodic_ns,
    legacy_preferences_ns,
    procedural_ns,
    semantic_ns,
    user_namespaces,
)
from .scoring import rank
from .store import MemoryBackend
from .types import EPISODIC, PROCEDURAL, SEMANTIC, MemoryItem, now_iso
from ..log_utils import memory_logger


class MemoryKeeper:
    """一个用户、一份配置的记忆管家。"""

    def __init__(
        self,
        backend: MemoryBackend,
        user_id: str = "default_user",
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self.backend = backend
        self.user_id = user_id or "default_user"
        self.config = config or DEFAULT_MEMORY_CONFIG

    # ---------------- 内部工具 ----------------

    def _iter_items(self, namespace: Sequence[str], batch: int = 200, cap: int = 2000):
        """分页扫描命名空间，脏记录直接跳过。"""
        items: List[MemoryItem] = []
        for offset in range(0, cap, batch):
            records = self.backend.search(namespace, limit=batch, offset=offset) or []
            for record in records:
                item = MemoryItem.from_dict(record.value)
                if item is not None:
                    items.append(item)
            if len(records) < batch:
                break
        return items

    def _persist(self, item: MemoryItem) -> MemoryItem:
        item.updated_at = now_iso()
        self.backend.put(self._ns_of(item), item.store_key, item.to_dict())
        return item

    def _ns_of(self, item: MemoryItem):
        from .namespaces import type_ns

        return type_ns(self.user_id, item.type)

    # ---------------- 语义记忆（WARM） ----------------

    def _valid_semantic(self, key: str) -> List[MemoryItem]:
        return [
            m
            for m in self._iter_items(semantic_ns(self.user_id))
            if m.key == key and m.is_valid()
        ]

    def write_semantic(
        self,
        key: str,
        value: str,
        *,
        confidence: float = 0.6,
        evidence: str = "",
        source: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Optional[MemoryItem]:
        """写入一条语义记忆。

        冲突处理：同一 key 下已有有效记忆时，旧值标记失效；
        若旧值置信度 >= ``immutable_confidence`` 且新值更低，则**拒绝写入**。

        同值不产生新版本：把同一句话再说一遍属于**强化**而不是改主意，
        只把置信度取高者，避免历史版本名额被重复内容挤占。
        """
        if not key or value is None:
            return None

        existing = self._valid_semantic(key)
        for old in existing:
            if old.confidence >= self.config.immutable_confidence and confidence < old.confidence:
                memory_logger.info(
                    f"Skip semantic write for '{key}': existing high-confidence "
                    f"({old.confidence}) not superseded by {confidence}"
                )
                return None

        same = next((old for old in existing if old.content == str(value)), None)
        if same is not None:
            if confidence > same.confidence:
                same.confidence = confidence
                same.evidence = evidence or same.evidence
                self._persist(same)
                memory_logger.info(
                    f"Reinforce semantic '{key}': confidence {same.confidence} → {confidence}"
                )
            return same

        item = MemoryItem(
            type=SEMANTIC,
            content=str(value),
            summary=f"{key}={value}",
            key=key,
            confidence=confidence,
            evidence=evidence,
            source=source or {},
            tags=list(tags or []),
        )
        for old in existing:
            old.invalidate(by=item.id)
            self._persist(old)
        self._persist(item)
        self._trim_semantic_history(key)
        return item

    def merge_preferences(
        self, updates: Dict[str, Any], *, source: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """批量合并偏好，返回实际写入的 key 列表。"""
        written = []
        for key, value in (updates or {}).items():
            if self.write_semantic(str(key), str(value), confidence=0.8, source=source):
                written.append(str(key))
        if written:
            self._sync_preference_projection()
        return written

    def load_preferences(self) -> Dict[str, Any]:
        """当前有效的语义记忆投影成偏好字典（同 key 取最新）。"""
        prefs: Dict[str, Any] = {}
        items = sorted(
            [m for m in self._iter_items(semantic_ns(self.user_id)) if m.is_valid()],
            key=lambda m: m.updated_at,
        )
        for item in items:
            if item.key:
                prefs[item.key] = item.content
        return prefs

    def _sync_preference_projection(self) -> None:
        """把语义记忆投影到旧偏好命名空间，供不读本体的链路直接取用。"""
        self.backend.put(
            legacy_preferences_ns(self.user_id),
            LEGACY_PREFERENCES_KEY,
            self.load_preferences(),
        )

    def migrate_legacy_preferences(self) -> int:
        """把旧偏好命名空间里的字典提升为语义记忆；返回迁移条数。

        旧命名空间本质是语义记忆的**投影**（见 `_sync_preference_projection`），
        所以已经有有效语义记录的 key 一律跳过。否则每次装配 agent 都会重迁一遍：
        旧值带着 0.6 的置信度把 0.8 的那条顶掉，反复重启会让置信度来回抖动，
        还会把历史版本名额耗在完全一样的内容上。
        """
        raw = self.backend.get(legacy_preferences_ns(self.user_id), LEGACY_PREFERENCES_KEY)
        if not isinstance(raw, dict) or not raw:
            return 0
        current = self.load_preferences()
        moved = 0
        for key, value in raw.items():
            if value is None or str(key) in current:
                continue
            if self.write_semantic(
                str(key), str(value), confidence=0.6, evidence="migrated from legacy preferences"
            ):
                moved += 1
        return moved

    def _trim_semantic_history(self, key: str) -> None:
        history = [m for m in self._iter_items(semantic_ns(self.user_id)) if m.key == key]
        history.sort(key=lambda m: m.created_at, reverse=True)
        for stale in history[self.config.max_semantic_history :]:
            self.backend.delete(semantic_ns(self.user_id), stale.store_key)

    # ---------------- 情节记忆 ----------------

    def archive_episode(
        self,
        thread_id: str,
        summary: str,
        content: str = "",
        *,
        source: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Optional[MemoryItem]:
        """归档一次会话情节；同一 thread_id 重复归档是幂等更新。

        缺少 thread_id 时直接跳过——否则所有会话都会写进同一个 ``ep_unknown``
        互相覆盖（这是 ERP 项目踩过的坑）。
        """
        if not thread_id or not summary:
            return None
        summary = summary[: self.config.episode_summary_chars]
        key = f"ep_{thread_id}"
        namespace = episodic_ns(self.user_id)
        existing = self.backend.get(namespace, key)
        item = MemoryItem.from_dict(existing)
        if item is None:
            item = MemoryItem(
                id=key,
                type=EPISODIC,
                content=content or summary,
                summary=summary,
                ttl_days=self.config.episode_ttl_days,
                confidence=0.9,
                source=source or {},
                tags=list(tags or []),
            )
        else:
            item.summary = summary
            item.content = content or item.content
            item.source = source or item.source
            item.tags = list(tags or item.tags)
        self._persist(item)
        self._evict_episodes()
        return item

    def _evict_episodes(self) -> None:
        namespace = episodic_ns(self.user_id)
        items = sorted(self._iter_items(namespace), key=lambda m: m.created_at, reverse=True)
        for stale in items[self.config.max_episodes :]:
            self.backend.delete(namespace, stale.store_key)

    # ---------------- 程序记忆 ----------------

    def write_procedural(
        self,
        content: str,
        summary: str = "",
        *,
        confidence: float = 0.7,
        source: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> MemoryItem:
        item = MemoryItem(
            type=PROCEDURAL,
            content=content,
            summary=summary or content[: self.config.episode_summary_chars],
            confidence=confidence,
            source=source or {},
            tags=list(tags or []),
        )
        return self._persist(item)

    # ---------------- WARM 注入 ----------------

    def build_warm_brief(self) -> str:
        """生成注入系统提示词的 WARM 摘要（含截断，不做无损压缩）。"""
        lines: List[str] = []
        size = 0
        limit = self.config.warm_brief_chars

        prefs = self.load_preferences()
        if prefs:
            chunk = "用户偏好：" + "；".join(
                f"{k}={v}" for k, v in list(prefs.items())[:12]
            )
            lines.append(chunk[: self.config.warm_item_chars * 4])
            size += len(lines[-1])

        episodes = [
            m
            for m in self._iter_items(episodic_ns(self.user_id))
            if m.is_valid() and m.tier(self.config.warm_episode_days) == "warm"
        ]
        episodes.sort(key=lambda m: m.created_at, reverse=True)
        for episode in episodes[: self.config.max_warm_episodes]:
            stamp = episode.created_at[:10]
            line = f"- [{stamp}] {episode.summary[: self.config.warm_item_chars]}"
            if size + len(line) + 1 > limit:
                lines.append("（近况已截断，更多请用 read_memory 检索）")
                break
            lines.append(line)
            size += len(line) + 1

        return "\n".join(lines)[:limit]

    # ---------------- COLD 检索 ----------------

    def retrieve(self, query: str, k: Optional[int] = None, *, now: Optional[datetime] = None):
        """按需检索长期记忆，命中后会 touch（累计引用频次）。"""
        pool: List[MemoryItem] = []
        for namespace in user_namespaces(self.user_id):
            pool.extend(self._iter_items(namespace))
        hits = rank(query, pool, self.config, k or self.config.retrieval_k, now)
        for item in hits:
            item.touch()
            self._persist(item)
        return hits

    # ---------------- 遗忘 ----------------

    def sweep(self, *, now: Optional[datetime] = None) -> Dict[str, int]:
        """TTL 过期 + 超量淘汰；返回各类清理条数。"""
        now = now or datetime.now()
        removed = {"expired": 0, "evicted": 0}

        for namespace in user_namespaces(self.user_id):
            for item in self._iter_items(namespace):
                if item.is_expired(now):
                    self.backend.delete(namespace, item.store_key)
                    removed["expired"] += 1

        self._evict_episodes()
        for item in self._iter_items(procedural_ns(self.user_id))[self.config.max_episodes :]:
            self.backend.delete(procedural_ns(self.user_id), item.store_key)
            removed["evicted"] += 1
        return removed

    # ---------------- 调试 ----------------

    def stats(self) -> Dict[str, int]:
        """分层统计：`<type>` 是有效条数，`<type>_history` 是被失效的旧版本。

        两层分开数——把历史版本算进有效数会让面板显示 6 条、实际只有 2 条可用。
        """
        out: Dict[str, int] = {}
        for name, ns in (
            ("semantic", semantic_ns),
            ("episodic", episodic_ns),
            ("procedural", procedural_ns),
        ):
            items = self._iter_items(ns(self.user_id))
            valid = sum(1 for item in items if item.is_valid())
            out[name] = valid
            out[f"{name}_history"] = len(items) - valid
        return out
