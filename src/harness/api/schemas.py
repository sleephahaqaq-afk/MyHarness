"""请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field("default", max_length=128)
    user_id: str = Field("default_user", max_length=128)


class HealthResponse(BaseModel):
    status: str
    model: Optional[str] = None
    agent_ready: bool
    missing_config: List[str] = Field(default_factory=list)
    # 搜索不可用不影响对话，但要单独报——否则只会体现为「模型说它不能联网」
    web_search_ready: bool = False
    web_search_missing: List[str] = Field(default_factory=list)


class MemoryItemResponse(BaseModel):
    """记忆条目。``valid=False`` 表示是被双时态失效掉的历史版本。"""

    id: str
    tier: str
    type: str
    key: Optional[str] = None
    content: str
    confidence: float
    createdAt: str
    valid: bool = True


class MemoryResponse(BaseModel):
    user_id: str
    preferences: Dict[str, Any]
    warm_brief: str
    stats: Dict[str, int]
    items: List[MemoryItemResponse]


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str


class SubAgentResponse(BaseModel):
    name: str
    description: str
    tools: List[str]
    sections: List[str]
