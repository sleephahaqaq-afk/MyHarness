"""子 Agent 配置加载器。

职责：
1. 读取 ``configs/*.yaml`` 并校验必填字段；
2. 把 tools 里的字符串映射成实际工具对象（精确 > 分组前缀 > 子串兜底）；
3. 解析 ``interrupt_on``（人工审批）与 ``output_format``（输出契约）；
4. 生成主 Agent 的委派上下文协议提示词。

工具匹配为什么收敛到"精确 > 前缀 > 子串"：
子串匹配会让 ``order`` 命中 ``reorder_item`` 这类意外包含该片段的工具，
导致子 Agent 拿到不该有的写权限；因此先精确、再按 ``_`` 边界前缀，最后才子串兜底。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from ..log_utils import agent_logger
from ..middlewares.clock import ClockMiddleware

DEFAULT_CONFIG_DIR = Path(__file__).parent / "configs"

REQUIRED_FIELDS = ("name", "description", "system_prompt", "tools")


def _validate(config: Dict[str, Any]) -> bool:
    return all(config.get(field) for field in REQUIRED_FIELDS)


def validate_config(config: Dict[str, Any]) -> List[str]:
    """返回配置的问题列表；空列表表示合法。"""
    problems: List[str] = []
    for field in REQUIRED_FIELDS:
        if not config.get(field):
            problems.append(f"缺少必填字段: {field}")
    if config.get("tools") is not None and not isinstance(config["tools"], list):
        problems.append("tools 必须是列表")
    output_format = _output_format_of(config)
    if isinstance(output_format, dict):
        sections = output_format.get("sections")
        if sections is not None and (
            not isinstance(sections, list)
            or not all(isinstance(s, str) for s in sections)
        ):
            problems.append("output_format.sections 必须是字符串列表")
    return problems


def _output_format_of(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """支持顶层 output_format 或 context_protocol.output_format。"""
    output_format = config.get("output_format")
    if isinstance(output_format, dict):
        return output_format
    protocol = config.get("context_protocol")
    if isinstance(protocol, dict) and isinstance(protocol.get("output_format"), dict):
        return protocol["output_format"]
    return None


def load_subagent_configs(config_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """加载并校验目录下的所有 YAML 配置。"""
    directory = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    configs: List[Dict[str, Any]] = []
    if not directory.is_dir():
        agent_logger.warning(f"子 Agent 配置目录不存在: {directory}")
        return configs

    for yaml_file in sorted(directory.glob("*.yaml")):
        try:
            with yaml_file.open("r", encoding="utf-8") as handle:
                config = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            agent_logger.error(f"加载子 Agent 配置失败 {yaml_file}: {exc}")
            continue

        if not isinstance(config, dict):
            agent_logger.warning(f"跳过非法配置（不是映射）: {yaml_file}")
            continue

        problems = validate_config(config)
        if problems:
            agent_logger.warning(f"跳过配置 {yaml_file}: {'; '.join(problems)}")
            continue

        configs.append(config)
        agent_logger.info(f"Loaded subagent config: {config['name']}")
    return configs


def _match_tools(pattern: str, all_tools: Sequence[Any]) -> List[Any]:
    pattern_name = str(pattern or "").strip()
    if not pattern_name:
        return []

    exact = [t for t in all_tools if getattr(t, "name", "") == pattern_name]
    if exact:
        return exact
    prefix = [t for t in all_tools if str(getattr(t, "name", "")).startswith(pattern_name + "_")]
    if prefix:
        return prefix
    return [t for t in all_tools if pattern_name in str(getattr(t, "name", ""))]


def resolve_subagent_tools(
    configs: List[Dict[str, Any]], all_tools: Sequence[Any]
) -> List[Dict[str, Any]]:
    """把配置里的工具模式解析成实际工具对象，产出 SubAgent 规格。"""
    specs: List[Dict[str, Any]] = []

    for config in configs:
        matched: List[Any] = []
        for pattern in config.get("tools", []):
            hits = _match_tools(pattern, all_tools)
            if not hits:
                agent_logger.warning(
                    f"Subagent '{config.get('name')}' tool pattern '{pattern}' matched no tool"
                )
            for tool_obj in hits:
                if tool_obj not in matched:
                    matched.append(tool_obj)

        spec: Dict[str, Any] = {
            "name": config["name"],
            "description": config["description"],
            "system_prompt": config["system_prompt"] + build_output_contract_prompt(config),
            "tools": matched,
            # 子 Agent 是独立的图，主 Agent 的中间件不会作用到它；不挂时钟它会
            # 靠训练截止日期猜「今天」，把已发生的时间窗判成未来而拒绝检索。
            "middleware": [ClockMiddleware()],
        }
        interrupt_on = _parse_interrupt_on(config)
        if interrupt_on:
            spec["interrupt_on"] = interrupt_on
        specs.append(spec)
    return specs


def _parse_interrupt_on(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = config.get("interrupt_on")
    if not isinstance(raw, dict) or not raw:
        return None
    parsed: Dict[str, Any] = {}
    for tool_name, tool_config in raw.items():
        if isinstance(tool_config, dict):
            parsed[tool_name] = {
                "allowed_decisions": tool_config.get("allowed_decisions", ["approve", "reject"])
            }
            if "description" in tool_config:
                parsed[tool_name]["description"] = tool_config["description"]
    return parsed


def build_output_contract_prompt(config: Dict[str, Any]) -> str:
    """把 output_format 变成子 Agent 必须遵守的输出契约提示词。"""
    output_format = _output_format_of(config)
    if not isinstance(output_format, dict):
        return ""
    sections = output_format.get("sections") or []
    if not sections:
        return ""

    fmt_type = output_format.get("type", "structured_report")
    fmt = output_format.get("format", "markdown")
    lines = [
        "\n\n## 输出契约（必须严格遵守）",
        f"最终返回必须符合以下契约（类型：{fmt_type}，格式：{fmt}）：",
    ]
    lines.extend(f"{i}. **{section}**" for i, section in enumerate(sections, 1))
    lines.append("主 Agent 会按此契约校验；缺失任一 section 视为不合格并触发返工。")
    return "\n".join(lines)


def get_delegation_context_prompt(configs: List[Dict[str, Any]]) -> str:
    """生成主 Agent 的委派上下文协议（告诉它委派时要带什么）。"""
    sections: List[str] = []
    for config in configs:
        protocol = config.get("context_protocol")
        if not isinstance(protocol, dict):
            continue
        input_ctx = protocol.get("input_context") or []
        if not input_ctx:
            continue
        lines = [f"\n### 委派给 {config['name']} 时的上下文传递要求"]
        for field_def in input_ctx:
            if not isinstance(field_def, dict):
                continue
            field = field_def.get("field", "")
            desc = field_def.get("description", "")
            marker = "**[必填]**" if field_def.get("required") else "[可选]"
            lines.append(f"- {marker} `{field}`: {desc}")
        sections.append("\n".join(lines))

    if not sections:
        return ""
    return "\n## 子 Agent 委派上下文协议\n" + "\n".join(sections)
