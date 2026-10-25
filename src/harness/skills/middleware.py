"""每次模型调用前刷新技能目录（含缓存的 Agent Session 也刷新）。"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from ..log_utils import skills_logger
from .catalog import CATALOG_SLOT, SkillCatalog


class ProgressiveSkillsMiddleware(AgentMiddleware):
    """把 ``CATALOG_SLOT`` 替换成当前目录；找不到槽位就追加一块。"""

    def __init__(self, catalog: SkillCatalog) -> None:
        self.catalog = catalog

    @property
    def name(self) -> str:
        return "ProgressiveSkillsMiddleware"

    def _refresh(self, request: Any) -> Any:
        text = self.catalog.index()
        blocks = list(request.system_message.content_blocks) if request.system_message else []
        found = False
        for i, block in enumerate(blocks):
            if block.get("type") == "text" and CATALOG_SLOT in block.get("text", ""):
                blocks[i] = {**block, "text": block["text"].replace(CATALOG_SLOT, text)}
                found = True
        if not found:
            blocks.append({"type": "text", "text": text})
        return request.override(system_message=SystemMessage(content=blocks))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._refresh(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(await asyncio.to_thread(self._refresh, request))
