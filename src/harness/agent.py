"""基座装配入口。

一次调用把四块能力装上：middlewares / memory / skills / subagents。

用法（最小）：

    from harness.agent import build_agent
    from harness.memory.store import InMemoryBackend

    agent = build_agent(memory_backend=InMemoryBackend())
    agent.invoke({"messages": [{"role": "user", "content": "帮我调研…"}]},
                 config={"configurable": {"thread_id": "t-1"}})

``thread_id`` 一定要给：没有它情节记忆无法归档（中间件会跳过而不是写成 ep_unknown）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence

from deepagents import create_deep_agent

from .config import HarnessConfig, get_chat_model
from .log_utils import agent_logger
from .memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from .memory.keeper import MemoryKeeper
from .memory.prompts import MEMORY_USAGE_PROMPT, WARM_MEMORY_SLOT
from .memory.store import InMemoryBackend, LangGraphStoreAdapter, MemoryBackend
from .memory.tools import make_memory_tools
from .middlewares.clock import CLOCK_SLOT, ClockMiddleware
from .middlewares.context_injection import CONTEXT_SLOT, ContextInjectionMiddleware
from .middlewares.harness_phase import PHASE_SLOT, HarnessPhaseMiddleware, load_harness_config
from .middlewares.memory_consolidation import MemoryConsolidationMiddleware
from .middlewares.memory_update import MemoryUpdateMiddleware
from .middlewares.tools_summarization import ToolsSummarizationMiddleware
from .middlewares.warm_memory import WarmMemoryMiddleware
from .prompts import MAIN_SYSTEM_PROMPT
from .schema import HarnessContext
from .skills.catalog import CATALOG_SLOT, SkillCatalog, attach_to_subagents
from .skills.middleware import ProgressiveSkillsMiddleware
from .subagents.loader import (
    get_delegation_context_prompt,
    load_subagent_configs,
    resolve_subagent_tools,
)
from .tools.web import default_web_tools

MEMORY_AGENTS_FILE = Path(__file__).parent / "memory" / "AGENTS.md"


def precompute_context(
    memory_backend: MemoryBackend,
    user_id: str = "default_user",
    config: Optional[MemoryConfig] = None,
) -> HarnessContext:
    """在装配前预读一次 WARM 记忆，构造请求上下文。"""
    ctx = HarnessContext(user_id=user_id)
    if memory_backend is None:
        return ctx
    try:
        keeper = MemoryKeeper(memory_backend, user_id, config or DEFAULT_MEMORY_CONFIG)
        keeper.migrate_legacy_preferences()
        ctx.preferences = keeper.load_preferences()
        ctx.warm_memory = keeper.build_warm_brief()
    except Exception as exc:
        agent_logger.warning(f"Failed to preload memory for {user_id}: {exc}")
    return ctx


def build_agent(
    *,
    model: Any = None,
    config: Optional[HarnessConfig] = None,
    context: Optional[HarnessContext] = None,
    tools: Optional[Sequence[Any]] = None,
    include_web_tools: bool = True,
    memory_backend: Optional[MemoryBackend] = None,
    memory_config: Optional[MemoryConfig] = None,
    store: Any = None,
    checkpointer: Any = None,
    backend: Any = None,
    skills_dir: Optional[Path] = None,
    subagent_config_dir: Optional[Path] = None,
    extra_middleware: Optional[Sequence[Any]] = None,
    interrupt_on: Optional[dict] = None,
    name: str = "harness-agent",
    enable_memory_file: bool = True,
):
    """组装一个带完整基座能力的 Deep Agent。

    Args:
        model: 语言模型，缺省用 :func:`get_chat_model` 从 .env 构造。
        config: 基座配置，缺省从 .env 读取（缺失即报错）。
        context: 用户上下文，缺省按 ``default_user`` 预读记忆。
        tools: 业务工具（BaseTool / 函数工具）。
        include_web_tools: 是否装上内置联网工具（web_search / web_fetch）。
            子 Agent 配置里声明了这两个工具时关掉会让它们拿到空工具集。
        memory_backend: 记忆后端；缺省 InMemoryBackend（进程内，不持久）。
            传入 LangGraph Store 时会自动用 :class:`LangGraphStoreAdapter` 包装。
        memory_config: 记忆分层与治理参数。
        store: LangGraph Store，透传给 create_deep_agent（子 Agent / 长期存储）。
        checkpointer: LangGraph checkpointer（HOT 层会话持久化）。
        backend: deepagents Backend 实例（沙箱 / 文件系统路由）。
        skills_dir: 内置技能根目录，缺省 config.skills_dir。
        subagent_config_dir: 子 Agent 配置目录，缺省 config.subagent_config_dir。
        extra_middleware: 追加的中间件（排在内置中间件之后）。
        interrupt_on: 需要人工审批的工具配置。
        name: Agent 名称。
        enable_memory_file: 是否把 memory/AGENTS.md 作为记忆说明挂载。

    Returns:
        CompiledStateGraph
    """
    cfg = config or HarnessConfig.from_env(require_llm=model is None)
    mcfg = memory_config or DEFAULT_MEMORY_CONFIG
    user_id = (context.user_id if context else None) or "default_user"

    # 1. 模型
    chat_model = model if model is not None else get_chat_model(cfg)

    # 2. 记忆后端
    if memory_backend is None and store is not None:
        memory_backend = LangGraphStoreAdapter(store)
    if memory_backend is None:
        agent_logger.warning(
            "未提供 memory_backend，使用 InMemoryBackend（进程内、重启即失）。"
            "生产请传入持久化后端或 LangGraph Store。"
        )
        memory_backend = InMemoryBackend()

    def keeper_factory(user: str = user_id) -> MemoryKeeper:
        return MemoryKeeper(memory_backend, user, mcfg)

    # 3. 上下文
    ctx = context or precompute_context(memory_backend, user_id, mcfg)

    # 4. 技能（渐进披露）
    catalog = SkillCatalog(skills_dir or cfg.skills_dir, backend=memory_backend, user_id=user_id)
    skill_tools = catalog.tools()

    # 5. 工具集
    all_tools: List[Any] = list(tools or [])
    if include_web_tools:
        known = {str(getattr(t, "name", "")) for t in all_tools}
        all_tools.extend(t for t in default_web_tools() if t.name not in known)
    all_tools.extend(skill_tools)
    if mcfg.memory_tools_enabled:
        all_tools.extend(make_memory_tools(lambda: keeper_factory(user_id), mcfg))

    # 6. 子 Agent
    subagent_configs = load_subagent_configs(subagent_config_dir or cfg.subagent_config_dir)
    subagents = resolve_subagent_tools(subagent_configs, all_tools)
    attach_to_subagents(subagents, catalog, skill_tools)
    delegation_prompt = get_delegation_context_prompt(subagent_configs)

    # 7. 中间件栈
    harness_cfg = load_harness_config(cfg.harness_yaml)
    middlewares: List[Any] = [
        HarnessPhaseMiddleware(harness_cfg),
        ClockMiddleware(),
        ContextInjectionMiddleware(ctx),
        WarmMemoryMiddleware(lambda: keeper_factory(user_id)),
        ProgressiveSkillsMiddleware(catalog),
        MemoryUpdateMiddleware(lambda: keeper_factory(user_id)),
        MemoryConsolidationMiddleware(lambda: keeper_factory(user_id)),
        ToolsSummarizationMiddleware(cfg.tool_output_chars),
    ]
    if extra_middleware:
        middlewares.extend(extra_middleware)

    # 8. 系统提示词（槽位在每次模型调用时被对应中间件替换）
    system_prompt = MAIN_SYSTEM_PROMPT.format(user_id=ctx.user_id, username=ctx.username)
    system_prompt += f"\n{CLOCK_SLOT}\n{CONTEXT_SLOT}\n{WARM_MEMORY_SLOT}\n{PHASE_SLOT}\n{CATALOG_SLOT}"
    if mcfg.memory_tools_enabled:
        system_prompt += MEMORY_USAGE_PROMPT
    if delegation_prompt:
        system_prompt += delegation_prompt

    agent = create_deep_agent(
        model=chat_model,
        tools=all_tools,
        system_prompt=system_prompt,
        middleware=middlewares,
        subagents=subagents or None,
        skills=None,  # 由 ProgressiveSkillsMiddleware 接管，避免双重加载
        memory=[str(MEMORY_AGENTS_FILE)] if enable_memory_file and MEMORY_AGENTS_FILE.is_file() else None,
        backend=backend,
        interrupt_on=interrupt_on,
        checkpointer=checkpointer,
        store=store,
        name=name,
    )

    agent_logger.info(
        f"Harness agent ready: tools={len(all_tools)}, subagents={len(subagents)}, "
        f"middlewares={len(middlewares)}, skills_dir={catalog.root}"
    )
    return agent


__all__ = ["build_agent", "precompute_context", "MEMORY_AGENTS_FILE"]
