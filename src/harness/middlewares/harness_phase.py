"""Harness 阶段状态机：Planning → Executing → Review → Result。

阶段与检查项来自 ``harness_config.yaml``，不是硬编码在代码里：
改提示策略不需要改 Python。中间件在每次模型调用前把当前阶段的检查项
注入系统提示词，after_model 时推进阶段。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from ..config import DEFAULT_HARNESS_YAML
from ..log_utils import middleware_logger
from ..schema import Phase, HarnessState, next_phase

PHASE_SLOT = "<!-- LIVE_HARNESS_PHASE -->"


def load_harness_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取 Harness DSL 配置；文件缺失时返回空配置（由调用方决定是否兜底）。"""
    target = Path(path) if path else DEFAULT_HARNESS_YAML
    if not target.is_file():
        middleware_logger.warning(f"Harness 配置不存在: {target}")
        return {}
    try:
        import yaml

        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        middleware_logger.warning(f"Harness 配置解析失败 {target}: {exc}")
        return {}


def _phase_block(phase: Phase, config: Dict[str, Any]) -> str:
    phases = config.get("phases") if isinstance(config.get("phases"), dict) else {}
    section = phases.get(phase.value) if isinstance(phases.get(phase.value), dict) else {}
    lines = [f"当前阶段：{phase.value}"]
    instruction = section.get("instruction")
    if instruction:
        lines.append(str(instruction))
    checklist = section.get("checklist")
    if isinstance(checklist, list) and checklist:
        lines.append("本阶段检查项：")
        lines.extend(f"- {item}" for item in checklist)
    return "\n".join(lines)


class HarnessPhaseMiddleware(AgentMiddleware):
    """维护 phase 状态，并把当前阶段的检查项注入系统提示词。"""

    state_schema = HarnessState

    def __init__(self, config: Optional[Dict[str, Any]] = None, config_path: Optional[Path] = None):
        self.config = config if config is not None else load_harness_config(config_path)

    @property
    def name(self) -> str:
        return "HarnessPhaseMiddleware"

    def before_agent(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        return {"phase": Phase.PLANNING.value, "plan": [], "review": {}}

    def after_model(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        current = state.get("phase") if isinstance(state, dict) else None
        try:
            phase = Phase(current) if current else Phase.PLANNING
        except ValueError:
            phase = Phase.PLANNING
        return {"phase": next_phase(phase).value}

    def _inject(self, request: Any) -> Any:
        state = getattr(request, "state", None) or {}
        raw = state.get("phase") if isinstance(state, dict) else None
        try:
            phase = Phase(raw) if raw else Phase.PLANNING
        except ValueError:
            phase = Phase.PLANNING
        block = _phase_block(phase, self.config)

        blocks = list(request.system_message.content_blocks) if request.system_message else []
        found = False
        for i, item in enumerate(blocks):
            if item.get("type") == "text" and PHASE_SLOT in item.get("text", ""):
                blocks[i] = {**item, "text": item["text"].replace(PHASE_SLOT, block)}
                found = True
        if not found:
            blocks.append({"type": "text", "text": block})
        return request.override(system_message=SystemMessage(content=blocks))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._inject(request))

    # 异步版：agent.astream_events / ainvoke 走这条路径，缺了会抛 NotImplementedError
    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._inject(request))

    async def abefore_agent(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.before_agent, state, runtime)

    async def aafter_model(self, state: Any, runtime: Any) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.after_model, state, runtime)
