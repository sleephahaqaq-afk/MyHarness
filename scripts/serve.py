"""启动 HTTP 服务。

    python scripts/serve.py                # 127.0.0.1:8000
    python scripts/serve.py --port 8001    # 换端口（前端 vite.config.ts 记得同步）
    python scripts/serve.py --reload       # 改代码自动重载
    python scripts/serve.py --demo         # 不需要 LLM_API_KEY，用脚本模型跑通链路

``--demo`` 只在本进程里把 agent 换成脚本化模型，不改 .env、不改基座代码。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
for path in (str(SRC), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import uvicorn  # noqa: E402

from harness.env_utils import load_dotenv  # noqa: E402


def install_demo_agent() -> None:
    """把进程级 state 的 agent 换成脚本模型（--demo 专用）。"""
    from harness.api.server import state
    from harness.memory.config import DEFAULT_MEMORY_CONFIG
    from harness.schema import HarnessContext
    from demo_model import DemoChatModel

    from harness.agent import build_agent

    try:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
    except Exception:  # pragma: no cover
        checkpointer = None

    state._agent = build_agent(
        model=DemoChatModel(),
        memory_backend=state.backend,
        memory_config=DEFAULT_MEMORY_CONFIG,
        context=HarnessContext(user_id="demo", username="演示用户"),
        skills_dir=state.skills_dir,
        checkpointer=checkpointer,
        name="harness-demo-agent",
    )
    state._agent_error = None


def main() -> int:
    argv = sys.argv[1:]
    host = "127.0.0.1"
    port = 8000
    reload = "--reload" in argv
    demo = "--demo" in argv

    for index, item in enumerate(argv):
        if item == "--port" and index + 1 < len(argv):
            port = int(argv[index + 1])
        elif item == "--host" and index + 1 < len(argv):
            host = argv[index + 1]

    if demo and reload:
        print("[serve] --demo 与 --reload 不能同时用（重载会丢掉注入的模型）")
        return 2

    env_file = load_dotenv()
    print(f"[serve] .env: {env_file or '未找到（/api/health 会提示缺失项）'}")

    if demo:
        import harness.api.server as server_module

        install_demo_agent()
        print(f"[serve] 演示模式：agent 已注入 DemoChatModel（user_id=demo，无需 API key）")
        # 让 uvicorn 复用已注入 agent 的那个模块对象
        uvicorn.run(server_module.app, host=host, port=port, log_level="info")
        return 0

    print(f"[serve] http://{host}:{port}  (docs: /docs)")
    uvicorn.run(
        "harness.api.server:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(SRC)] if reload else None,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
