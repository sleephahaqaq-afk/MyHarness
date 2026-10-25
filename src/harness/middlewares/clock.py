"""当前时间注入。

为什么需要：模型自己不知道「今天」，只能靠训练截止日期猜。没有这个中间件时，
子 Agent 会把 2026-10-18~25 这样的时间窗判成「未来」而直接拒绝检索——搜索工具
明明可用，它一次都没调。

两个设计约束：
- **每次模型调用现算**，不能写死在系统提示词里：服务可能连跑几天，日期会漂移。
- **子 Agent 也要挂**：deepagents 的子 Agent 有独立的 system prompt 与图，
  主 Agent 的中间件不会作用到它身上（`SubAgent.middleware` 才是入口）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

CLOCK_SLOT = "<!-- LIVE_CLOCK -->"

TIMEZONE = "Asia/Shanghai"
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def render_clock(now: Optional[datetime] = None) -> str:
    """渲染一行给模型看的当前时间。"""
    current = now or datetime.now(ZoneInfo(TIMEZONE))
    offset = current.strftime("%z")
    offset_text = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    weekday = WEEKDAYS[current.weekday()]
    return (
        f"当前时间：{current.strftime('%Y-%m-%d')}（{weekday}）"
        f"{current.strftime('%H:%M')} {offset_text}。"
        "涉及「最近/最新/本月」的任务以这个时间为基准；"
        "晚于它的时间窗尚未发生，不要编造，也不要拿别的时段替代。"
    )


class ClockMiddleware(AgentMiddleware):
    """把当前时间注入系统提示词（每轮刷新）。"""

    def __init__(self, slot: str = CLOCK_SLOT, timezone: str = TIMEZONE) -> None:
        self.slot = slot
        self.timezone = timezone

    @property
    def name(self) -> str:
        return "ClockMiddleware"

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def _inject(self, request: Any) -> Any:
        block = render_clock(self._now())
        blocks = list(request.system_message.content_blocks) if request.system_message else []
        for index, item in enumerate(blocks):
            if item.get("type") == "text" and self.slot in item.get("text", ""):
                blocks[index] = {**item, "text": item["text"].replace(self.slot, block)}
                return request.override(system_message=SystemMessage(content=blocks))
        # 子 Agent 的系统提示词来自 YAML，没有槽位，直接追加
        blocks.append({"type": "text", "text": block})
        return request.override(system_message=SystemMessage(content=blocks))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._inject(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._inject(request))
