"""FastAPI 服务：SSE 对话 + 记忆 / 技能 / 子 Agent 查询。

启动：
    python scripts/serve.py
或
    uvicorn harness.api.server:app --port 8000

没有配置 LLM 时服务照样能起：`/api/health` 会报 `agent_ready=false` 和缺失项，
`/api/skills`、`/api/subagents`、`/api/memory` 仍然可用；`/api/chat` 返回一条
可读的错误消息而不是 500。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..config import HarnessConfig
from ..env_utils import ConfigError, optional_env
from ..log_utils import agent_logger
from ..memory.config import DEFAULT_MEMORY_CONFIG
from ..memory.keeper import MemoryKeeper
from ..memory.store import FileBackend
from ..skills.catalog import SkillCatalog
from ..subagents.loader import load_subagent_configs
from ..tools.web import search_config_missing
from .events import EventBridge
from .schemas import ChatRequest, HealthResponse, MemoryResponse, SkillResponse, SubAgentResponse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / ".data"
MEMORY_FILE = DATA_DIR / "memory.json"


class HarnessState:
    """进程级单例：记忆后端、技能目录、延迟构建的 agent。"""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.backend = FileBackend(MEMORY_FILE)
        self.config: Optional[HarnessConfig] = None
        self.skills_dir: Path = PROJECT_ROOT / "skills"
        self.catalog = SkillCatalog(self.skills_dir, backend=self.backend)
        self._agent: Any = None
        self._agent_error: Optional[str] = None
        self._lock = threading.Lock()

    # ---------- 配置 ----------

    def config_or_none(self) -> Optional[HarnessConfig]:
        if self.config is None:
            try:
                self.config = HarnessConfig.from_env(require_llm=True)
            except ConfigError:
                return None
        return self.config

    def missing_config(self) -> List[str]:
        required = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]
        return [name for name in required if not optional_env(name)]

    def keeper(self, user_id: str) -> MemoryKeeper:
        return MemoryKeeper(self.backend, user_id, DEFAULT_MEMORY_CONFIG)

    # ---------- Agent ----------

    def ensure_agent(self) -> Any:
        """延迟构建；失败时抛 ConfigError / RuntimeError 供调用方转成事件。"""
        if self._agent is not None:
            return self._agent
        with self._lock:
            if self._agent is not None:
                return self._agent

            cfg = self.config_or_none()
            if cfg is None:
                missing = "、".join(self.missing_config()) or "LLM 配置"
                raise ConfigError(f"缺少 {missing}；请复制 .env.example 为 .env 并填写后重启。")

            from ..agent import build_agent

            try:
                from langgraph.checkpoint.memory import InMemorySaver

                checkpointer: Any = InMemorySaver()
            except Exception:  # pragma: no cover - 老版本 langgraph
                checkpointer = None

            agent_logger.info(f"Building agent (model={cfg.llm.chat_model}) …")
            self._agent = build_agent(
                config=cfg,
                memory_backend=self.backend,
                checkpointer=checkpointer,
                name="harness-api-agent",
            )
            self._agent_error = None
            return self._agent


state = HarnessState()


def create_app() -> FastAPI:
    app = FastAPI(title="Harness API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.harness = state

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        cfg = state.config_or_none()
        search_missing = search_config_missing()
        return HealthResponse(
            status="ok",
            model=cfg.llm.chat_model if cfg else None,
            agent_ready=state._agent is not None,
            missing_config=state.missing_config(),
            web_search_ready=not search_missing,
            web_search_missing=search_missing,
        )

    @app.post("/api/chat")
    def chat(request: ChatRequest):
        bridge = EventBridge(user_id=request.user_id, session_id=request.session_id)

        async def generate():
            try:
                agent = state.ensure_agent()
            except (ConfigError, RuntimeError) as exc:
                async for frame in bridge.error(f"后端未就绪：{exc}"):
                    yield frame
                return

            try:
                async for frame in bridge.translate(agent, request.message):
                    yield frame
            except Exception as exc:  # 图执行异常也要以事件形式回传
                agent_logger.error(f"chat failed: {type(exc).__name__}: {exc}")
                async for frame in bridge.error(f"执行失败：{type(exc).__name__}: {exc}"):
                    yield frame

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/memory", response_model=MemoryResponse)
    def memory(user_id: str = Query("default_user", max_length=128)) -> MemoryResponse:
        keeper = state.keeper(user_id)
        items = []
        for namespace in (
            ("memories", user_id, "semantic"),
            ("memories", user_id, "episodic"),
            ("memories", user_id, "procedural"),
        ):
            for record in state.backend.search(namespace, limit=200):
                value = record.value
                items.append(
                    {
                        "id": value.get("id", record.key),
                        "tier": "warm" if value.get("type") == "semantic" else "cold",
                        "type": value.get("type", "semantic"),
                        "key": value.get("key") or None,
                        "content": value.get("summary") or value.get("content", ""),
                        "confidence": float(value.get("confidence") or 0),
                        "createdAt": str(value.get("created_at", ""))[:10],
                        "valid": value.get("invalidated_at") is None,
                    }
                )
        # 有效的在前，同组内按日期倒序
        items.sort(key=lambda item: (item["valid"], item["createdAt"]), reverse=True)
        return MemoryResponse(
            user_id=user_id,
            preferences=keeper.load_preferences(),
            warm_brief=keeper.build_warm_brief(),
            stats=keeper.stats(),
            items=items,
        )

    @app.get("/api/skills", response_model=List[SkillResponse])
    def skills() -> List[SkillResponse]:
        entries, _ = state.catalog.entries()
        return [
            SkillResponse(id=e["id"], name=e["name"], description=e["description"]) for e in entries
        ]

    @app.get("/api/subagents", response_model=List[SubAgentResponse])
    def subagents() -> List[SubAgentResponse]:
        result = []
        for config in load_subagent_configs():
            protocol = config.get("context_protocol") or {}
            output = (protocol.get("output_format") or config.get("output_format") or {})
            result.append(
                SubAgentResponse(
                    name=config["name"],
                    description=str(config.get("description", "")).strip(),
                    tools=list(config.get("tools") or []),
                    sections=list(output.get("sections") or []),
                )
            )
        return result

    @app.get("/api/sessions")
    def sessions() -> List[dict]:
        # 会话状态在 InMemorySaver 里，没有查询接口；这里只给个占位便于前端接入
        return []

    return app


app = create_app()
