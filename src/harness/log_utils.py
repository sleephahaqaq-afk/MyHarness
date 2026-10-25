"""统一日志出口。

基座内所有模块共用两个 logger，方便使用者按需重定向或静音。
"""
from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def _build(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


agent_logger = _build("harness.agent")
middleware_logger = _build("harness.middleware")
memory_logger = _build("harness.memory")
skills_logger = _build("harness.skills")
