"""端到端装配测试：用脚本化模型跑真实 LangGraph 图，验证四块能力都接上了。

这里不做"看起来像"的断言：技能目录、阶段提示、WARM 记忆都取自模型实际收到的
系统提示词，记忆写入则直接查后端。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from harness.agent import build_agent, precompute_context
from harness.memory.keeper import MemoryKeeper
from harness.memory.namespaces import episodic_ns
from harness.memory.store import InMemoryBackend
from harness.schema import HarnessContext

from fake_model import ScriptedChatModel

SKILLS_DIR = __file__.rsplit("tests", 1)[0] + "skills"


@tool
def ping(text: str) -> str:
    """Echo the input back, used by tests."""
    return f"pong:{text}"


def _model(reply: str = "已收到") -> ScriptedChatModel:
    ScriptedChatModel.log.clear()
    ScriptedChatModel.tool_names.clear()
    return ScriptedChatModel(queue=[AIMessage(content=reply)])


def test_build_agent_wires_tools_skills_and_subagents():
    ScriptedChatModel.log.clear()
    ScriptedChatModel.tool_names.clear()
    model = ScriptedChatModel(queue=[AIMessage(content="已收到")])
    agent = build_agent(
        model=model,
        memory_backend=InMemoryBackend(),
        tools=[ping],
        context=HarnessContext(user_id="u1", username="洋"),
        skills_dir=SKILLS_DIR,
    )
    assert agent is not None

    # 工具绑定发生在真正调用模型时
    agent.invoke(
        {"messages": [{"role": "user", "content": "ping 一下"}]},
        config={"configurable": {"thread_id": "t-0"}},
    )
    bound = set(ScriptedChatModel.tool_names)
    assert {"ping", "list_skills", "read_skill", "read_skill_resource"} <= bound
    assert {"read_memory", "remember"} <= bound


def test_invoke_injects_catalog_phase_and_warm_memory():
    backend = InMemoryBackend()
    MemoryKeeper(backend, "u1").merge_preferences({"output_format": "table"})
    model = _model()

    agent = build_agent(
        model=model,
        memory_backend=backend,
        context=HarnessContext(user_id="u1", username="洋"),
        skills_dir=SKILLS_DIR,
    )
    agent.invoke(
        {"messages": [{"role": "user", "content": "帮我整理一份报告"}]},
        config={"configurable": {"thread_id": "t-1"}},
    )

    system_prompts = "\n".join(ScriptedChatModel.log)
    assert "技能目录只含元数据" in system_prompts      # skills 目录已注入
    assert "当前阶段：planning" in system_prompts       # harness 阶段已注入
    assert "output_format=table" in system_prompts      # WARM 记忆已注入
    assert "当前用户：洋" in system_prompts             # 上下文已注入
    assert "<!-- LIVE_" not in system_prompts           # 槽位都被替换掉了


def test_invoke_writes_preference_and_archives_episode():
    backend = InMemoryBackend()
    model = _model("好的，之后用 markdown")

    agent = build_agent(
        model=model,
        memory_backend=backend,
        context=HarnessContext(user_id="u1", username="洋"),
        skills_dir=SKILLS_DIR,
    )
    agent.invoke(
        {"messages": [{"role": "user", "content": "以后都用 markdown 输出"}]},
        config={"configurable": {"thread_id": "t-77"}},
    )

    keeper = MemoryKeeper(backend, "u1")
    assert keeper.load_preferences().get("output_format") == "markdown"

    episodes = keeper._iter_items(episodic_ns("u1"))
    assert len(episodes) == 1
    assert "markdown" in episodes[0].summary


def test_precompute_context_loads_existing_memory():
    backend = InMemoryBackend()
    MemoryKeeper(backend, "u2").merge_preferences({"language": "zh"})

    ctx = precompute_context(backend, "u2")
    assert ctx.user_id == "u2"
    assert ctx.preferences["language"] == "zh"
    assert "language=zh" in ctx.warm_memory


def test_delegation_protocol_reaches_system_prompt():
    model = _model()
    agent = build_agent(
        model=model,
        memory_backend=InMemoryBackend(),
        context=HarnessContext(user_id="u1"),
        skills_dir=SKILLS_DIR,
    )
    agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-2"}},
    )

    system_prompts = "\n".join(ScriptedChatModel.log)
    assert "子 Agent 委派上下文协议" in system_prompts
    assert "委派给 research-analyst" in system_prompts
