"""子 Agent 装配测试：配置校验、工具匹配优先级、输出契约、委派协议、审批配置。"""
from __future__ import annotations

import textwrap

from harness.subagents.loader import (
    build_output_contract_prompt,
    get_delegation_context_prompt,
    load_subagent_configs,
    resolve_subagent_tools,
    validate_config,
)


class DummyTool:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, DummyTool) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


ALL_TOOLS = [
    DummyTool("web_search"),
    DummyTool("web_fetch"),
    DummyTool("order_create"),
    DummyTool("order_cancel"),
    DummyTool("reorder_item"),
]


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


VALID_YAML = """
    name: analyst
    description: 分析专员
    tools:
      - web_search
      - order
    system_prompt: |
      你是分析专员
"""


def test_missing_fields_are_reported():
    problems = validate_config({"name": "x", "tools": []})
    assert any("system_prompt" in p for p in problems)
    assert any("description" in p for p in problems)


def test_invalid_output_format_is_reported():
    problems = validate_config(
        {
            "name": "x",
            "description": "d",
            "system_prompt": "s",
            "tools": [],
            "output_format": {"sections": [1, 2]},
        }
    )
    assert any("sections" in p for p in problems)


def test_load_skips_invalid_and_keeps_valid(tmp_path):
    _write(tmp_path, "ok.yaml", VALID_YAML)
    _write(tmp_path, "bad.yaml", "name: broken\n")

    configs = load_subagent_configs(tmp_path)
    assert [c["name"] for c in configs] == ["analyst"]


def test_tool_matching_prefers_exact_then_prefix():
    configs = [
        {
            "name": "ops",
            "description": "d",
            "system_prompt": "s",
            "tools": ["web_search", "order"],
        }
    ]
    spec = resolve_subagent_tools(configs, ALL_TOOLS)[0]
    names = [t.name for t in spec["tools"]]

    assert "web_search" in names          # 精确命中
    assert "order_create" in names and "order_cancel" in names  # 前缀命中
    assert "reorder_item" not in names    # 子串兜底不会误伤写工具


def test_output_contract_is_injected_into_system_prompt():
    config = {
        "name": "writer",
        "output_format": {"sections": ["summary", "body"]},
    }
    contract = build_output_contract_prompt(config)
    spec = resolve_subagent_tools(
        [
            {
                "name": "writer",
                "description": "d",
                "system_prompt": "你是写手",
                "tools": [],
                "output_format": {"sections": ["summary", "body"]},
            }
        ],
        ALL_TOOLS,
    )[0]

    assert "输出契约" in contract
    assert "summary" in spec["system_prompt"]
    assert spec["system_prompt"].startswith("你是写手")


def test_delegation_prompt_lists_required_fields():
    configs = [
        {
            "name": "analyst",
            "context_protocol": {
                "input_context": [
                    {"field": "task_objective", "description": "目标", "required": True},
                    {"field": "scope", "description": "范围"},
                ]
            },
        }
    ]
    prompt = get_delegation_context_prompt(configs)
    assert "委派给 analyst" in prompt
    assert "**[必填]** `task_objective`" in prompt
    assert "[可选] `scope`" in prompt


def test_interrupt_on_is_parsed():
    configs = [
        {
            "name": "order-bot",
            "description": "d",
            "system_prompt": "s",
            "tools": ["order_create"],
            "interrupt_on": {
                "order_create": {"description": "下单需审批", "allowed_decisions": ["approve", "reject"]}
            },
        }
    ]
    spec = resolve_subagent_tools(configs, ALL_TOOLS)[0]
    assert spec["interrupt_on"]["order_create"]["description"] == "下单需审批"


def test_resolve_reports_unmatched_pattern(caplog):
    configs = [
        {"name": "x", "description": "d", "system_prompt": "s", "tools": ["nonexistent_tool"]}
    ]
    spec = resolve_subagent_tools(configs, ALL_TOOLS)[0]
    assert spec["tools"] == []


# ---------------- 真实配置（仓库内 yaml） ----------------

from pathlib import Path  # noqa: E402

from harness.memory.config import MemoryConfig  # noqa: E402
from harness.memory.tools import make_memory_tools  # noqa: E402
from harness.skills.catalog import SkillCatalog  # noqa: E402
from harness.tools.web import default_web_tools  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _real_tools():
    catalog = SkillCatalog(PROJECT_ROOT / "skills")
    return (
        default_web_tools()
        + catalog.tools()
        + make_memory_tools(lambda: None, MemoryConfig())
    )


def test_shipped_configs_all_resolve_their_tools():
    """仓库里的每个 yaml 都必须能匹配到工具，否则子 Agent 会拿到空工具集。"""
    configs = load_subagent_configs(PROJECT_ROOT / "src/harness/subagents/configs")
    specs = {spec["name"]: spec for spec in resolve_subagent_tools(configs, _real_tools())}

    assert {"ai-news-scout", "research-analyst", "report-writer"} <= set(specs)
    for name, spec in specs.items():
        assert spec["tools"], f"{name} 没有匹配到任何工具"


def test_ai_news_scout_declares_web_tools_and_contract():
    configs = load_subagent_configs(PROJECT_ROOT / "src/harness/subagents/configs")
    specs = {spec["name"]: spec for spec in resolve_subagent_tools(configs, _real_tools())}
    scout = specs["ai-news-scout"]

    assert {"web_search", "web_fetch", "read_skill"} <= {t.name for t in scout["tools"]}
    assert "输出契约" in scout["system_prompt"]
    for section in ("scan_window", "top_items", "unverified", "sources"):
        assert section in scout["system_prompt"]

    config = next(c for c in configs if c["name"] == "ai-news-scout")
    delegation = get_delegation_context_prompt([config])
    assert "task_objective" not in delegation  # 侦察员要的是 topic，不是任务编号
    assert "**[必填]** `topic`" in delegation
    assert "[可选] `time_window`" in delegation



def test_subagents_carry_clock_middleware():
    """子 Agent 是独立图，主 Agent 的时钟中间件不会传下去。

    漏挂的后果：`ai-news-scout` 把 2026-10-18~25 判成「未来」，
    一次 web_search 都不调，直接输出「无法检索」。
    """
    from harness.middlewares.clock import ClockMiddleware

    specs = resolve_subagent_tools(load_subagent_configs(), ALL_TOOLS)
    assert specs
    for spec in specs:
        names = [m.name for m in spec.get("middleware", [])]
        assert "ClockMiddleware" in names, f"{spec['name']} 没挂时钟"
        assert any(isinstance(m, ClockMiddleware) for m in spec["middleware"])
