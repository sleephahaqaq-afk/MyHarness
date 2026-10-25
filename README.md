# MyHarness — 通用 Agent 基座

基于 **deepagents + LangGraph + LangChain** 的 Agent 基座，把四类横切能力做成可插拔模块：
**middlewares / memory / skills / subagents**。业务代码只提供模型、工具和 YAML 配置。

参考了 `D:\Projects\py\ERP-AGENT-open-source` 的 Harness Engineering 架构，但去掉了它的
业务耦合（ERP 工具、MongoDB、Docker 沙箱、DeepSeek/JEV 路由），保留并重写了四块能力。

---

## 环境

```
Python: D:\Projects\py_environment\aistudy_py3.14\python.exe   (3.14.6)
依赖:   deepagents 0.7.32 / langchain 1.3.17 / langgraph 1.2.11 / langchain-openai 1.6.0
```

> deepagents 官方声明依赖 `langchain>=1.4.7`，实测在 1.3.17 下导入与运行时均正常
> （`create_deep_agent` / `SubAgent` / `AgentMiddleware` / `backends` 全可用），
> 因此用 `pip install --no-deps` 装入，**没有升级共用环境的 langchain 生态**。

```bash
pip install -r requirements.txt
cp .env.example .env        # 填写 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
python scripts/smoke.py     # 离线冒烟（脚本模型，不消耗 token）
python -m pytest tests -q   # 41 项测试
```

---

## 目录结构

```
src/harness/
├─ agent.py              装配入口 build_agent() / precompute_context()
├─ config.py             HarnessConfig（.env 注入，零回退）
├─ env_utils.py          require_env / optional_env（缺失即报 ConfigError）
├─ schema.py             Phase / HarnessContext / HarnessState
├─ runtime_context.py    thread_id 提取（Runtime.execution_info → langgraph config）
├─ harness_config.yaml   阶段检查项 DSL（改提示策略不用改 Python）
├─ memory/               三层记忆
│  ├─ types.py           MemoryItem（双时态 + 可溯源 + 可治理）
│  ├─ namespaces.py      (memories, user_id, semantic|episodic|procedural)
│  ├─ store.py           MemoryBackend 协议 + InMemory / File / LangGraph 适配
│  ├─ scoring.py         文本相关度 + 时间衰减 + 频次 + 置信度
│  ├─ keeper.py          MemoryKeeper：写入 / 冲突 / TTL / 淘汰 / 检索 / WARM 摘要
│  ├─ extractor.py       规则抽取（临时表达与否定表达跳过）
│  ├─ tools.py           read_memory / remember
│  └─ AGENTS.md          给模型看的记忆使用说明
├─ skills/               渐进披露：目录 → 正文 → 资源
│  ├─ catalog.py         SkillCatalog + list_skills/read_skill/read_skill_resource
│  └─ middleware.py      ProgressiveSkillsMiddleware（槽位刷新）
├─ subagents/            YAML 声明式子 Agent
│  ├─ loader.py          校验 / 工具匹配 / 输出契约 / 委派协议 / interrupt_on
│  └─ configs/           ai-news-scout.yaml、research-analyst.yaml、report-writer.yaml
├─ tools/
│  └─ web.py             web_search（服务端内置搜索）+ web_fetch（含 SSRF 防护）
├─ api/                  HTTP 层（FastAPI + SSE）
│  ├─ server.py          端点 + 进程级 HarnessState（延迟构建 agent）
│  ├─ events.py          astream_events → EngineEvent 翻译
│  └─ schemas.py         ChatRequest / Health / Memory / Skill / SubAgent
└─ middlewares/
   ├─ harness_phase.py      阶段状态机 + 检查项注入
   ├─ context_injection.py  用户上下文（thread 级隔离）
   ├─ warm_memory.py        WARM 记忆刷新
   ├─ memory_update.py      偏好提取（after_agent）
   ├─ memory_consolidation.py 情节归档（after_agent）
   └─ tools_summarization.py 超长工具输出截断
skills/core/             内置技能（report-style / memory-hygiene）
skills/research/         内置技能（ai-news-digest 情报采集规则）
tests/                    66 项测试 + scripted fake model（含流式 _astream）
scripts/serve.py          启动 HTTP 服务（--demo 无需 API key）
scripts/demo_model.py     脚本化模型，仅 --demo 注入，不进 src/
scripts/smoke.py          端到端冒烟
```

---

## 四个模块

### memory：HOT / WARM / COLD

| 层 | 载体 | 谁负责 |
|---|---|---|
| HOT | 会话状态 + checkpoint | LangGraph（checkpointer） |
| WARM | 每次模型调用前注入系统提示词 | `WarmMemoryMiddleware` + `build_warm_brief()` |
| COLD | 按需检索 | `read_memory` 工具 + `MemoryKeeper.retrieve()` |

- **冲突**：同一 `key` 的新值让旧值失效，保留有限历史；置信度 ≥ `MEMORY_IMMUTABLE_CONFIDENCE`
  （默认 1.0）的事实不会被更低置信度覆盖。
- **归档**：`thread_id` 缺失时**跳过**归档，不退化成 `ep_unknown`（ERP 项目踩过的坑）。
- **遗忘**：TTL 过期 + 数量淘汰（`sweep()`）。
- **后端**：`MemoryBackend` 协议，默认 `InMemoryBackend`（进程内、重启即失）；
  本地持久化用 `FileBackend`，接 LangGraph Store 用 `LangGraphStoreAdapter`。

### skills：目录 → 正文 → 资源

系统提示词里只有元数据 JSON 行（约 1.5 KB 量级），正文和资源由 `read_skill` /
`read_skill_resource` 按需拉取。安全约束：相对路径拒绝 `..`/`.`/`:`/空字节、拒绝符号链接、
只放行文本后缀、屏蔽 `credentials.json` / `secrets.json`、三级字节上限、错误不回显路径。

### subagents：YAML 声明式

必填 `name / description / system_prompt / tools`。工具匹配 **精确 > `_` 前缀 > 子串兜底**——
子串兜底会让 `order` 命中 `reorder_item`，凭空给出写权限。可选 `output_format`（输出契约，
会注入子 Agent 提示词）、`context_protocol.input_context`（生成主 Agent 委派协议）、
`interrupt_on`（人工审批）。

仓库内置三个示例：

| name | 触发 | 工具 | 输出契约 |
|---|---|---|---|
| `ai-news-scout` | AI 最新动态 / 模型发布 / 论文速递 | web_search, web_fetch, read_skill | 7 节（scan_window → sources） |
| `research-analyst` | 调研 / 查资料 / 事实核查 | web_search, web_fetch, read_memory | 5 节（question → open_questions） |
| `report-writer` | 写报告 / 整理成文 | read_memory, read_skill, list_skills | 5 节（title → next_actions） |

### middlewares
按列表顺序包裹模型调用；`after_*` 钩子逆序执行：

`HarnessPhase → Clock → ContextInjection → WarmMemory → ProgressiveSkills → MemoryUpdate → MemoryConsolidation → ToolsSummarization`

- 阶段检查项来自 `harness_config.yaml`，不硬编码在 Python 里。
- `ClockMiddleware` 每次模型调用注入「当前时间」。**漏了它模型就只能靠训练截止日期猜今天**——
  `ai-news-scout` 曾把 2026-10-18~25 判成「未来」，一次 `web_search` 都不调就回答「无法检索」。
  子 Agent 是独立的图，主 Agent 的中间件不会传下去，所以 `SubAgent.middleware` 里也挂了一份。

### tools：联网

`web_search` 走 **LLM_BASE_URL 对应服务的 `/responses` 内置搜索**（复用 `LLM_API_KEY`，
不需要额外的 Tavily/Bing key），端点可用 `WEB_SEARCH_URL` 覆盖；`time_range`
（day/week/month/any）会拼成中文时间窗写进检索指令。

`web_fetch` 自己做 HTML→文本 + 截断，并带 **SSRF 防护**：只放行 http/https，
主机解析出的所有 IP 必须是公网地址（挡住 127.0.0.1 / 10.x / 192.168.x /
169.254.169.254 / ::1 / *.local）。

两者失败都返回**可读错误字符串**而不是抛异常——抛异常会中断整张图，
模型看到"搜索失败: 未配置 WEB_SEARCH_MODEL"还能换个办法继续。

`WEB_SEARCH_MODEL` 是**必填**，缺了工具会在发请求前禁用自己。判断逻辑收敛在
`web.search_config_missing()`，`/api/health` 复用同一份——否则会出现「健康检查说一切正常，
但模型说它不能联网」这种最难查的故障。端点支持 `{"type": "web_search"}`（`web_search_preview`
会被拒），所以换中转站或模型前先用一行 curl 试通再改 `.env`。

启用条件（`.env`）：

```dotenv
LLM_BASE_URL=https://api.deepseek.com/v1   # /responses 由它推导
LLM_API_KEY=...                            # 搜索复用同一个 key
WEB_SEARCH_MODEL=deepseek-chat             # 必须支持内置 web_search 工具
```

`build_agent(include_web_tools=False)` 可关闭；关掉后声明了这两个工具的子 Agent
会拿到空工具集（日志有 `matched no tool` 警告）。

---

## 用法

```python
from harness.agent import build_agent
from harness.memory.store import FileBackend
from harness.schema import HarnessContext

agent = build_agent(
    memory_backend=FileBackend(".data/memory.json"),
    context=HarnessContext(user_id="u1", username="洋"),
    tools=[my_tool],
    checkpointer=my_checkpointer,   # 可选，HOT 层持久化
)

agent.invoke(
    {"messages": [{"role": "user", "content": "帮我调研…"}]},
    config={"configurable": {"thread_id": "t-1"}},   # 一定要给，否则情节不归档
)
```

`build_agent` 的关键参数：`model`（不给则从 .env 构造）、`memory_backend`、`tools`、
`include_web_tools`（默认 True）、`skills_dir`、`subagent_config_dir`、`extra_middleware`、
`interrupt_on`、`backend`（deepagents 沙箱/文件系统路由）、`store`、`checkpointer`。

---

## 扩展约定

1. **新技能**：`skills/<scope>/<skill>/SKILL.md`，frontmatter 必须有 `name` + `description`
   （目录索引只读 frontmatter，没 description 的 md 不会被列为技能）。
2. **新子 Agent**：`src/harness/subagents/configs/*.yaml`，四必填字段 + 精确工具名；
   需要格式约束时写 `output_format.sections`。
3. **新中间件**：继承 `AgentMiddleware`，加到 `middlewares/` 并通过 `extra_middleware` 传入；
   注入系统提示词请用**槽位**（`<!-- LIVE_XXX -->`），不要直接拼接内容。
4. **新配置**：一律走 `.env`，用 `require_env()`，不要写 magic number 或 silent fallback。

---

## 启动服务

### 1. 后端（FastAPI + SSE）

```bash
# 需要真实模型：先把 .env 里的 LLM_API_KEY 换成真 key
python scripts/serve.py                 # http://127.0.0.1:8000  文档 /docs
python scripts/serve.py --port 8001     # 换端口（前端 vite.config.ts 同步改）
python scripts/serve.py --reload        # 改代码自动重载

# 没有 key 也能把整条链路点一遍：脚本化模型，不请求任何外部服务
python scripts/serve.py --demo
```

`--demo` 只是在本进程里把 agent 换成 `scripts/demo_model.py` 的脚本模型，
**不改 .env、不改基座代码、没有隐式回退**；它和 `--reload` 互斥（重载会丢掉注入的模型）。

没有配置 key 时服务照样能起：`/api/health` 报 `agent_ready=false` 和缺失项，
`/api/skills`、`/api/subagents`、`/api/memory` 仍然可用，`/api/chat` 回一条可读错误事件。

| 端点 | 说明 |
|---|---|
| `GET /api/health` | `status` / `model` / `agent_ready` / `missing_config` / `web_search_ready` / `web_search_missing` |
| `POST /api/chat` | SSE 流；body `{message, user_id, session_id}` |
| `GET /api/memory?user_id=` | WARM brief + 偏好 + 分层统计 + 明细 |
| `GET /api/skills` | 技能目录（只读 frontmatter 元数据） |
| `GET /api/subagents` | 子 Agent 名 / 工具 / 输出契约 sections |
| `GET /api/sessions` | 占位（会话在 checkpointer 里，暂无查询接口） |

`/api/chat` 的事件协议（前端 `EngineEvent` 一一对应）：

```
assistant_start → delta* → assistant_end → done
phase / tool_start / tool_end / delegate_start / delegate_end / memory / system
```

两处关键实现，改的时候别看漏：

- 中间件**必须同时实现同步与异步钩子**。`astream_events` 走异步路径，
  只写 `wrap_model_call` 会直接抛 `NotImplementedError`（这条已被 `tests/test_api.py` 锁住）。
- `on_chat_model_end` 有 delta 兜底。模型不支持流式时 langchain-core 的
  `_should_stream()` 返回 False，整轮只有一个 `on_chat_model_end`；没有兜底前端会渲染空气泡。

### 2. 前端（Vite dev server）

```bash
cd frontend && npm run dev      # http://localhost:5173，/api 已代理到 127.0.0.1:8000
```

默认走真实后端。要纯前端演示（不启动后端）：

```bash
VITE_USE_MOCK=1 npm run dev
```

不做"连不上 backend 就悄悄退回 mock"——那种隐式回退会让你误以为后端通了。
后端没起时请求会失败，UI 渲染成红色错误卡。

---

## 前端：Harness Console

`frontend/` 是基座的可视化工作台，**Vite + React 19 + TypeScript，样式全部手写 CSS**
（不引 UI 库，才能把 Shopify 品牌语言的墨绿底 / Lime 强调 / 大圆角 / 1px 细描边做准）。

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # 产物在 dist/（~19 KB CSS + ~248 KB JS，gzip 后 4.5 + 78 KB）
```

界面三栏：

- **左**：会话列表 + 运行时状态（模型 / 记忆 / backend）+ 主题切换（深/浅）；
- **中**：四阶段进度条 + 消息流（工具调用卡可展开、子 Agent 委派卡带 glow）+ 输入区
  与快捷入口；
- **右**：记忆（WARM 偏好 / 近期情节 + COLD 归档）、技能目录、子 Agent 契约。

数据来源：默认打 `POST /api/chat`；`VITE_USE_MOCK=1` 时走本地 mock 引擎
（`src/lib/mockEngine.ts`），四套剧本按关键词选择——AI 动态走 `ai-news-scout` 委派、
报告走 `report-writer`、偏好类消息走 `remember` 写入、其余走 `read_memory` 检索。

---

## 与 ERP 项目的差异（本基座未包含）

| ERP 项目有 | 本基座 |
|---|---|
| MCP 工具桥、Docker 沙箱 7 层防护 | 未包含（用 `backend` 参数外挂） |
| FastAPI + SSE 服务层、Next.js 前端 | **已有** FastAPI + SSE（`src/harness/api/`）+ Vite/React 控制台 |
| 混合审查路由（deep/JEV）、RubricMiddleware 评审回路 | 只有阶段检查项注入，没有 grader 回路 |
| MongoDB 持久化、评测集 | 持久化给了 `FileBackend` / LangGraph Store 适配；评测集未包含 |

## 已知限制

- 偏好抽取走确定性规则，只覆盖 `output_format / language / verbosity / chart_type`
  四个维度；LLM 抽取接口预留但默认关闭。
- WARM 注入是**有界截断**（`warm_brief_chars`，默认 4000 字符），不是无损压缩。
- `MemoryKeeper` 统一入口不等于数据库事务，也没有分布式并发保证。
- 子 Agent 工具匹配的子串兜底仍有误匹配风险，写操作工具建议用精确名。
- `web_search` 依赖上游服务的 `/responses` 内置搜索能力；服务不支持时返回
  `搜索失败: ...`，不会静默降级成"凭记忆回答"。
- `web_fetch` 的 SSRF 校验基于**解析时**的 IP，不防 DNS 重绑定（需要固定出口代理才彻底）。
