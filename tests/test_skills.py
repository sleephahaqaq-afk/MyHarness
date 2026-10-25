"""技能渐进披露测试：目录索引、正文读取、路径与后缀安全、槽位注入。"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import SystemMessage

from harness.skills.catalog import (
    CATALOG_SLOT,
    SkillCatalog,
    allowed_resource,
    safe_relative,
)
from harness.skills.middleware import ProgressiveSkillsMiddleware

SKILLS_DIR = __file__.rsplit("tests", 1)[0] + "skills"


def test_catalog_indexes_skill_frontmatter_only():
    catalog = SkillCatalog(SKILLS_DIR)
    entries, warnings = catalog.entries()

    ids = [e["id"] for e in entries]
    assert any("report-style" in i for i in ids)
    assert any("memory-hygiene" in i for i in ids)
    # 目录只含元数据，不含正文
    assert all(set(e) == {"id", "name", "description"} for e in entries)
    assert "报告输出规范" not in json.dumps(entries, ensure_ascii=False)
    assert warnings == []


def test_read_skill_returns_full_body():
    catalog = SkillCatalog(SKILLS_DIR)
    entries, _ = catalog.entries()
    skill_id = next(e["id"] for e in entries if "report-style" in e["id"])

    text, location = catalog.read(skill_id)
    assert "报告输出规范" in text
    assert location.endswith("SKILL.md")


def test_read_skill_resource_and_guard_against_escape(tmp_path):
    root = tmp_path / "skills"
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\nbody\n", encoding="utf-8"
    )
    (root / "demo" / "note.md").write_text("resource text", encoding="utf-8")
    (root / "secret.txt").write_text("nope", encoding="utf-8")

    catalog = SkillCatalog(root)
    text, _ = catalog.read("builtin/demo/SKILL.md", "note.md")
    assert text == "resource text"

    with pytest.raises(ValueError):
        catalog.read("builtin/demo/SKILL.md", "../secret.txt")


def test_path_validators_reject_unsafe_inputs():
    for bad in ("../x", "a/../b", ".hidden", "C:\\x", "a:b", "", "a\x00b"):
        with pytest.raises(ValueError):
            safe_relative(bad)

    assert safe_relative("a/b.md") == "a/b.md"
    with pytest.raises(ValueError):
        allowed_resource("run.exe")
    with pytest.raises(ValueError):
        allowed_resource("secrets.json")


def test_tools_return_structured_errors_without_leaking_paths(tmp_path):
    root = tmp_path / "skills"
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo\n---\nbody\n", encoding="utf-8"
    )
    catalog = SkillCatalog(root)
    list_skills, read_skill, _ = catalog.tools()

    listing = json.loads(list_skills.invoke({"query": "demo", "limit": 10}))
    assert listing["success"] is True and listing["total"] == 1

    failure = json.loads(read_skill.invoke({"skill_id": "builtin/demo/../demo/SKILL.md"}))
    assert failure["success"] is False
    assert "demo/SKILL.md" not in failure["error"]  # 不回显具体路径


def test_middleware_replaces_catalog_slot():
    catalog = SkillCatalog(SKILLS_DIR)
    middleware = ProgressiveSkillsMiddleware(catalog)

    class Request:
        def __init__(self, blocks):
            self.system_message = SystemMessage(content=blocks)
            self.blocks = blocks

        def override(self, system_message=None, **kwargs):
            self.system_message = system_message
            return self

    request = Request([{"type": "text", "text": f"SYS {CATALOG_SLOT} END"}])
    refreshed = middleware._refresh(request)

    joined = "".join(
        block.get("text", "") for block in refreshed.system_message.content_blocks
    )
    assert CATALOG_SLOT not in joined
    assert "技能目录只含元数据" in joined
    assert joined.startswith("SYS ") and joined.endswith(" END")
