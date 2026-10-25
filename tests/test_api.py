"""HTTP 层测试：只读端点 + **异步**流式链路。

异步那条最关键——它曾经挂在一个真实 bug 上：中间件只实现了同步
`wrap_model_call`，`astream_events` 走异步路径时直接抛 NotImplementedError。
现在用脚本模型跑一遍真实图，防止再退化。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from harness.agent import build_agent
from harness.api.events import EventBridge
from harness.api.server import app
from harness.memory.store import InMemoryBackend
from harness.schema import HarnessContext

from fake_model import ScriptedChatModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PROJECT_ROOT / "skills"


def _frames(raw_frames):
    out = []
    for frame in raw_frames:
        assert frame.startswith("data: ")
        out.append(json.loads(frame[len("data: ") :]))
    return out


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "agent_ready" in body and "missing_config" in body


def test_skills_endpoint_lists_builtin_skills():
    client = TestClient(app)
    body = client.get("/api/skills").json()
    ids = [item["id"] for item in body]
    assert any("report-style" in i for i in ids)
    assert all({"id", "name", "description"} == set(item) for item in body)


def test_subagents_endpoint_exposes_contract_sections():
    client = TestClient(app)
    body = client.get("/api/subagents").json()
    by_name = {item["name"]: item for item in body}

    assert "ai-news-scout" in by_name
    scout = by_name["ai-news-scout"]
    assert "web_search" in scout["tools"]
    assert "top_items" in scout["sections"]


async def test_async_stream_translates_langgraph_events():
    """真实图 + 异步流：验证中间件异步实现没漏。"""
    ScriptedChatModel.log.clear()
    model = ScriptedChatModel(queue=[AIMessage(content="这是异步链路的回答")])
    agent = build_agent(
        model=model,
        memory_backend=InMemoryBackend(),
        context=HarnessContext(user_id="u-api", username="测试"),
        skills_dir=SKILLS_DIR,
    )

    bridge = EventBridge(user_id="u-api", session_id="t-async")
    raw = [frame async for frame in bridge.translate(agent, "你好")]
    events = _frames(raw)

    types = [event["type"] for event in events]
    assert "delta" in types, f"没有收到流式增量: {types}"
    assert types[-1] == "done"
    assert "system" not in types, f"异步链路报错了: {events}"

    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "这是异步链路的回答" in text


async def test_non_streaming_model_still_produces_one_delta():
    """模型不支持流式时（disable_streaming），整轮只有 on_chat_model_end。

    没有兜底的话前端会渲染出一个空的助手气泡——这条测试锁住兜底行为。
    """
    model = ScriptedChatModel(
        queue=[AIMessage(content="不支持流式也要能看到这句话")],
        disable_streaming=True,
    )
    agent = build_agent(
        model=model,
        memory_backend=InMemoryBackend(),
        context=HarnessContext(user_id="u-api", username="测试"),
        skills_dir=SKILLS_DIR,
    )

    bridge = EventBridge(user_id="u-api", session_id="t-nostream")
    events = _frames([frame async for frame in bridge.translate(agent, "你好")])

    deltas = [e for e in events if e["type"] == "delta"]
    assert len(deltas) == 1, f"兜底应只补一条 delta: {[e['type'] for e in events]}"
    assert "不支持流式也要能看到这句话" in deltas[0]["text"]
    assert [e["type"] for e in events][-1] == "done"


async def test_error_path_uses_system_event():
    bridge = EventBridge(user_id="u-api", session_id="t-err")
    events = _frames([frame async for frame in bridge.error("后端未就绪：缺少 LLM_API_KEY")])

    assert events[0]["type"] == "system"
    assert "LLM_API_KEY" in events[0]["text"]
    assert events[-1]["type"] == "done"
