"""Skills 渐进披露：目录 → 正文 → 资源。

与文件同步是两件事：本模块只控制"模型看到什么"，不负责把文件搬到沙箱。
目录绑定用户（builtin + 用户命名空间），不接受由工具参数指定根目录，
因此不会产生跨用户的技能越权读取。
"""
from .catalog import (
    SkillCatalog,
    CATALOG_SLOT,
    attach_to_subagents,
)

from .middleware import ProgressiveSkillsMiddleware

__all__ = [
    "SkillCatalog",
    "ProgressiveSkillsMiddleware",
    "CATALOG_SLOT",
    "attach_to_subagents",
]
