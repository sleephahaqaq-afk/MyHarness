"""环境变量加载与读取。

约定（与用户既有项目一致）：
- 所有运行时值来自 .env / 进程环境，代码里不写业务默认值；
- 缺失关键配置直接抛错，不做 silent fallback。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """必需配置缺失。"""


def load_dotenv(path: Optional[Path] = None, *, required: bool = False) -> Optional[Path]:
    """加载 .env 到 os.environ（不覆盖已存在的环境变量）。

    Args:
        path: .env 路径，默认项目根目录下的 .env。
        required: 为 True 时文件不存在直接抛错。
    """
    target = Path(path) if path else PROJECT_ROOT / ".env"
    if not target.is_file():
        if required:
            raise ConfigError(f"缺少环境文件: {target}")
        return None

    from dotenv import load_dotenv as _load

    _load(str(target), override=False)
    return target


def require_env(name: str) -> str:
    """读取必需配置，缺失即报错（零回退）。"""
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ConfigError(
            f"缺少必需配置项 {name}；请在 .env 或进程环境中提供，代码不做默认值回退。"
        )
    return value.strip()


def optional_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"配置项 {name} 不是整数: {raw!r}") from exc


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"配置项 {name} 不是浮点数: {raw!r}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
