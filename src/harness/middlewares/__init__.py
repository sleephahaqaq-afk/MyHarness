"""基座中间件集合。

执行顺序（create_deep_agent 按列表顺序包裹模型调用，after_* 钩子逆序执行）：

1. HarnessPhaseMiddleware   —— 阶段状态机 + 阶段 rubric 注入
2. ContextInjectionMiddleware —— 用户身份 / 上下文注入
3. WarmMemoryMiddleware     —— WARM 记忆刷新（每次模型调用前）
4. ProgressiveSkillsMiddleware —— 技能目录刷新（来自 skills 模块）
5. MemoryUpdateMiddleware   —— 偏好提取（after_agent）
6. MemoryConsolidationMiddleware —— 情节归档（after_agent）
7. ToolsSummarizationMiddleware —— 超长工具输出截断
"""
from .harness_phase import HarnessPhaseMiddleware, load_harness_config
from .context_injection import ContextInjectionMiddleware
from .warm_memory import WarmMemoryMiddleware
from .memory_update import MemoryUpdateMiddleware
from .memory_consolidation import MemoryConsolidationMiddleware
from .tools_summarization import ToolsSummarizationMiddleware

__all__ = [
    "HarnessPhaseMiddleware",
    "load_harness_config",
    "ContextInjectionMiddleware",
    "WarmMemoryMiddleware",
    "MemoryUpdateMiddleware",
    "MemoryConsolidationMiddleware",
    "ToolsSummarizationMiddleware",
]
