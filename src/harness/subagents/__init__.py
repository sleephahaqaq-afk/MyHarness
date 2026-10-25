"""子 Agent：YAML 声明式配置 → deepagents SubAgent 规格。"""
from .loader import (
    load_subagent_configs,
    resolve_subagent_tools,
    get_delegation_context_prompt,
    build_output_contract_prompt,
    validate_config,
    REQUIRED_FIELDS,
)

__all__ = [
    "load_subagent_configs",
    "resolve_subagent_tools",
    "get_delegation_context_prompt",
    "build_output_contract_prompt",
    "validate_config",
    "REQUIRED_FIELDS",
]
