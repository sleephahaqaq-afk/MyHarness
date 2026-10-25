"""冒烟脚本：不依赖真实模型也能验证整条装配链路。

    python scripts/smoke.py           # 用脚本化模型跑一轮（默认）
    python scripts/smoke.py --real    # 用 .env 里的真实模型跑一轮
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from harness.agent import build_agent  # noqa: E402
from harness.memory.keeper import MemoryKeeper  # noqa: E402
from harness.memory.store import FileBackend, InMemoryBackend  # noqa: E402
from harness.schema import HarnessContext  # noqa: E402

QUESTION = "以后都用 markdown 输出，帮我整理一份报告"


def _offline_model():
    from fake_model import ScriptedChatModel

    return ScriptedChatModel(queue=[AIMessage(content="已按 markdown 格式整理完成。")])


def main() -> int:
    use_real = "--real" in sys.argv
    backend = InMemoryBackend()

    if use_real:
        from harness.config import get_chat_model

        model = get_chat_model()
    else:
        model = _offline_model()

    agent = build_agent(
        model=model,
        memory_backend=backend,
        context=HarnessContext(user_id="smoke-user", username="冒烟用户"),
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content=QUESTION)]},
        config={"configurable": {"thread_id": "smoke-thread"}},
    )
    answer = result["messages"][-1]
    print("回答：", getattr(answer, "content", answer))

    keeper = MemoryKeeper(backend, "smoke-user")
    print("偏好：", keeper.load_preferences())
    print("记忆统计：", keeper.stats())
    print("WARM 摘要：", keeper.build_warm_brief()[:200] or "（空）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
