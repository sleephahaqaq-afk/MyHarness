"""记忆层测试：冲突失效、不可覆盖规则、情节归档、检索、遗忘、持久化。"""
from __future__ import annotations

from datetime import datetime, timedelta

from harness.memory import MemoryConfig, MemoryKeeper
from harness.memory.namespaces import episodic_ns, procedural_ns, semantic_ns
from harness.memory.store import FileBackend, InMemoryBackend


def _keeper(user: str = "u1", **overrides) -> MemoryKeeper:
    return MemoryKeeper(InMemoryBackend(), user, MemoryConfig(**overrides))


def test_semantic_conflict_invalidates_previous_value():
    keeper = _keeper()
    keeper.write_semantic("output_format", "table")
    keeper.write_semantic("output_format", "markdown")

    assert keeper.load_preferences()["output_format"] == "markdown"
    valid = [m for m in keeper._iter_items(semantic_ns("u1")) if m.is_valid()]
    assert len(valid) == 1 and valid[0].content == "markdown"


def test_high_confidence_fact_is_not_overridden_by_weaker_one():
    keeper = _keeper()
    keeper.write_semantic("language", "zh", confidence=1.0)

    rejected = keeper.write_semantic("language", "en", confidence=0.6)
    assert rejected is None
    assert keeper.load_preferences()["language"] == "zh"

    accepted = keeper.write_semantic("language", "en", confidence=1.0)
    assert accepted is not None
    assert keeper.load_preferences()["language"] == "en"


def test_semantic_history_is_capped():
    keeper = _keeper(max_semantic_history=2)
    for value in ("a", "b", "c", "d"):
        keeper.write_semantic("verbosity", value)
    history = [m for m in keeper._iter_items(semantic_ns("u1")) if m.key == "verbosity"]
    assert len(history) == 2


def test_episode_archive_is_idempotent_per_thread():
    keeper = _keeper()
    keeper.archive_episode("thread-1", "完成了供应商对比")
    keeper.archive_episode("thread-1", "完成了供应商对比（补充）")

    items = keeper._iter_items(episodic_ns("u1"))
    assert len(items) == 1
    assert "补充" in items[0].summary


def test_episode_archive_skipped_without_thread_id():
    keeper = _keeper()
    assert keeper.archive_episode("", "无 thread_id 的会话") is None
    assert keeper._iter_items(episodic_ns("u1")) == []


def test_warm_brief_contains_preferences_and_recent_episodes():
    keeper = _keeper()
    keeper.merge_preferences({"output_format": "table", "language": "zh"})
    keeper.archive_episode("thread-9", "整理季度报告")

    brief = keeper.build_warm_brief()
    assert "output_format=table" in brief
    assert "整理季度报告" in brief


def test_warm_brief_is_bounded():
    keeper = _keeper(warm_brief_chars=120)
    keeper.merge_preferences({f"k{i}": f"v{i}" for i in range(20)})
    assert len(keeper.build_warm_brief()) <= 120


def test_retrieve_ranks_and_touches():
    keeper = _keeper()
    keeper.write_procedural("对比供应商时先看交期，再看价格", tags=["采购"])
    keeper.write_procedural("图表统一用深色背景")

    hits = keeper.retrieve("供应商 对比")
    assert hits and "交期" in hits[0].content
    assert hits[0].access_count >= 1


def test_retrieve_ignores_noise():
    keeper = _keeper(min_retrieval_score=0.9)
    keeper.write_procedural("完全无关的一段内容")
    assert keeper.retrieve("量子计算") == []


def test_sweep_removes_expired_memories():
    keeper = _keeper()
    item = keeper.write_procedural("很早以前的经验")
    item.ttl_days = 1
    item.created_at = (datetime.now() - timedelta(days=10)).isoformat()
    keeper._persist(item)

    removed = keeper.sweep()
    assert removed["expired"] == 1
    assert keeper._iter_items(procedural_ns("u1")) == []


def test_file_backend_persists_across_instances(tmp_path):
    path = tmp_path / "memory.json"
    first = MemoryKeeper(FileBackend(path), "u1")
    first.write_semantic("output_format", "csv")

    second = MemoryKeeper(FileBackend(path), "u1")
    assert second.load_preferences()["output_format"] == "csv"


def test_preferences_projection_is_synced():
    keeper = _keeper()
    keeper.merge_preferences({"chart_type": "bar"})
    projection = keeper.backend.get(("user-preferences", "u1"), "preferences")
    assert projection == {"chart_type": "bar"}


def test_migrate_legacy_preferences():
    backend = InMemoryBackend()
    backend.put(("user-preferences", "u1"), "preferences", {"language": "en"})

    keeper = MemoryKeeper(backend, "u1")
    assert keeper.migrate_legacy_preferences() == 1
    assert keeper.load_preferences()["language"] == "en"


def test_stats_separate_valid_items_from_history():
    """面板显示的数字必须是「有效条数」，不能把失效的历史版本算进去。"""
    keeper = _keeper()
    keeper.write_semantic("language", "zh")
    keeper.write_semantic("language", "en")

    stats = keeper.stats()
    assert stats["semantic"] == 1
    assert stats["semantic_history"] == 1
    assert stats["procedural"] == 0


def test_same_value_does_not_create_new_version_and_keeps_confidence():
    """把同一句话说第二遍是强化，不是改主意——不该产生新历史版本。"""
    keeper = _keeper()
    keeper.write_semantic("language", "zh", confidence=0.8)
    keeper.write_semantic("language", "zh", confidence=0.8)

    items = [m for m in keeper._iter_items(semantic_ns("u1")) if m.key == "language"]
    assert len(items) == 1, f"同值重复写产生了 {len(items)} 条历史版本"

    keeper.write_semantic("language", "zh", confidence=0.95)
    items = [m for m in keeper._iter_items(semantic_ns("u1")) if m.key == "language"]
    assert len(items) == 1
    assert items[0].confidence == 0.95, "重复陈述应当把置信度抬到更高值"


def test_migrate_legacy_preferences_is_idempotent_across_restarts():
    """旧命名空间是语义记忆的投影，重复装配 agent 不能反复重迁。

    退化表现：每启动一次就把置信度从 0.8 打回 0.6，并吃掉一个历史版本名额。
    """
    backend = InMemoryBackend()
    first = MemoryKeeper(backend, "u1")
    first.merge_preferences({"language": "zh"})  # 写入语义 + 同步投影

    for _ in range(3):  # 模拟三次进程重启 → 三次 precompute_context
        MemoryKeeper(backend, "u1").migrate_legacy_preferences()

    items = [m for m in first._iter_items(semantic_ns("u1")) if m.key == "language"]
    assert len(items) == 1, f"重复迁移产生了 {len(items)} 条历史版本"
    assert items[0].confidence == 0.8, "迁移不该把置信度降级"
    assert first.load_preferences()["language"] == "zh"
