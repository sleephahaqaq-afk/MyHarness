"""基座运行配置。

设计要点：
- 所有运行时值（模型端点、密钥、模型名、各种阈值）来自 .env；
- 端点 / 密钥 / 模型名缺失直接抛 :class:`ConfigError`，不做 silent fallback；
- 路径类配置有仓库内默认位置（属于代码资产，不属于运行时值）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .env_utils import (
    ConfigError,
    env_float,
    env_int,
    load_dotenv,
    optional_env,
    require_env,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKILLS_DIR = PROJECT_ROOT / "skills"
DEFAULT_SUBAGENT_CONFIG_DIR = Path(__file__).parent / "subagents" / "configs"
DEFAULT_MEMORY_DIR = Path(__file__).parent / "memory"
DEFAULT_HARNESS_YAML = Path(__file__).parent / "harness_config.yaml"


@dataclass(frozen=True)
class LLMConfig:
    """模型入口（OpenAI 兼容协议）。"""

    base_url: str
    api_key: str
    chat_model: str
    temperature: float = 0.0
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class HarnessConfig:
    """基座全局配置。"""

    llm: LLMConfig

    skills_dir: Path = DEFAULT_SKILLS_DIR
    subagent_config_dir: Path = DEFAULT_SUBAGENT_CONFIG_DIR
    memory_dir: Path = DEFAULT_MEMORY_DIR
    harness_yaml: Path = DEFAULT_HARNESS_YAML

    max_model_calls: int = 40
    max_tool_calls: int = 80
    tool_output_chars: int = 8000

    @classmethod
    def from_env(
        cls,
        *,
        require_llm: bool = True,
        dotenv_path: Optional[Path] = None,
        require_dotenv: bool = False,
    ) -> "HarnessConfig":
        """从 .env 构建配置。

        Args:
            require_llm: 为 True 时 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 缺失即报错；
                调用方已自带 model 实例时传 False 即可（零回退原则只约束
                "基座自己造模型"这条路径，不拦外部注入模型）。
        """
        load_dotenv(dotenv_path, required=require_dotenv)
        if require_llm:
            llm = LLMConfig(
                base_url=require_env("LLM_BASE_URL"),
                api_key=require_env("LLM_API_KEY"),
                chat_model=require_env("LLM_MODEL"),
                temperature=env_float("LLM_TEMPERATURE", 0.0),
                timeout_seconds=env_float("LLM_TIMEOUT_SECONDS", 120.0),
            )
        else:
            llm = LLMConfig(
                base_url=optional_env("LLM_BASE_URL") or "",
                api_key=optional_env("LLM_API_KEY") or "",
                chat_model=optional_env("LLM_MODEL") or "",
                temperature=env_float("LLM_TEMPERATURE", 0.0),
                timeout_seconds=env_float("LLM_TIMEOUT_SECONDS", 120.0),
            )
        return cls(
            llm=llm,
            skills_dir=Path(optional_env("HARNESS_SKILLS_DIR") or DEFAULT_SKILLS_DIR),
            subagent_config_dir=Path(
                optional_env("HARNESS_SUBAGENT_DIR") or DEFAULT_SUBAGENT_CONFIG_DIR
            ),
            memory_dir=Path(optional_env("HARNESS_MEMORY_DIR") or DEFAULT_MEMORY_DIR),
            harness_yaml=Path(optional_env("HARNESS_YAML") or DEFAULT_HARNESS_YAML),
            max_model_calls=env_int("HARNESS_MAX_MODEL_CALLS", 40),
            max_tool_calls=env_int("HARNESS_MAX_TOOL_CALLS", 80),
            tool_output_chars=env_int("HARNESS_TOOL_OUTPUT_CHARS", 8000),
        )


def get_chat_model(config: Optional[HarnessConfig] = None, *, temperature: Optional[float] = None):
    """构造 OpenAI 兼容的 chat model。

    任何调用都要求 .env 已提供 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。
    """
    cfg = (config or HarnessConfig.from_env()).llm
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:  # pragma: no cover - 依赖缺失时显式报错
        raise ConfigError(
            "缺少 langchain-openai；请 pip install langchain-openai 后再构造模型。"
        ) from exc

    return ChatOpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.chat_model,
        temperature=cfg.temperature if temperature is None else temperature,
        timeout=cfg.timeout_seconds,
    )


__all__ = ["LLMConfig", "HarnessConfig", "ConfigError", "get_chat_model", "PROJECT_ROOT"]
