"""HTTP 层：把基座包成一个 SSE 服务。

设计要点：
- **服务能起得来，即使没配模型**：agent 延迟构建，技能/子 Agent/记忆查询不依赖模型；
- 事件协议和前端 `EngineEvent` 一一对应，不用前端做第二套解析；
- 记忆走 `FileBackend` 落盘，会话状态走 LangGraph `InMemorySaver`（进程内）。
"""

from .server import app, create_app

__all__ = ["app", "create_app"]
