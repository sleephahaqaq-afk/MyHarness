import type { EngineEvent, MemoryItem, Phase } from "./types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function* chunk(text: string, size = 3): Generator<string> {
  for (let i = 0; i < text.length; i += size) yield text.slice(i, i + size);
}

async function* typeOut(id: string, text: string, delay = 12): AsyncGenerator<EngineEvent> {
  for (const piece of chunk(text)) {
    yield { type: "delta", id, text: piece };
    await sleep(delay);
  }
}

let counter = 0;
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${++counter}`;

function memoryItem(partial: Partial<MemoryItem> & { content: string }): MemoryItem {
  return {
    id: uid("m"),
    tier: partial.tier ?? "warm",
    type: partial.type ?? "semantic",
    key: partial.key,
    content: partial.content,
    confidence: partial.confidence ?? 0.8,
    createdAt: new Date().toISOString().slice(0, 10),
  };
}

/** AI 情报：委派 ai-news-scout，走 web_search / web_fetch */
async function* aiNewsScript(input: string): AsyncGenerator<EngineEvent> {
  const msg1 = uid("msg");
  yield { type: "phase", phase: "planning" };
  yield { type: "assistant_start", id: msg1 };
  yield* typeOut(
    msg1,
    `先定口径再检索：时间窗取最近 7 天，来源优先级为官方博客 / GitHub Release / arXiv，媒体报道只作补充。这条需求我委派给 ai-news-scout，它会按 7 段契约返回。`,
  );
  yield { type: "assistant_end", id: msg1 };

  const msg2 = uid("msg");
  yield { type: "phase", phase: "executing" };
  yield { type: "assistant_start", id: msg2 };

  const delegateId = uid("dlg");
  yield {
    type: "delegate_start",
    messageId: msg2,
    delegate: {
      id: delegateId,
      agent: "ai-news-scout",
      task: input.slice(0, 60) || "检索最近一周 AI 领域动态",
      tools: ["web_search", "web_fetch", "read_skill"],
      status: "running",
    },
  };
  await sleep(500);

  const searchId = uid("tool");
  yield {
    type: "tool_start",
    messageId: msg2,
    tool: {
      id: searchId,
      name: "web_search",
      args: 'query="AI 模型发布 最近7天" time_range="week"',
      status: "running",
    },
  };
  await sleep(1200);
  yield {
    type: "tool_end",
    messageId: msg2,
    toolId: searchId,
    durationMs: 1180,
    result:
      "命中 12 条：官方博客 4 条（含 2 个模型卡）、GitHub Release 3 条、arXiv 2 篇、媒体 3 篇。最早一条为 10-19。",
  };

  const fetchId = uid("tool");
  yield {
    type: "tool_start",
    messageId: msg2,
    tool: {
      id: fetchId,
      name: "web_fetch",
      args: 'url="https://example.ai/blog/model-card" max_chars=6000',
      status: "running",
    },
  };
  await sleep(900);
  yield {
    type: "tool_end",
    messageId: msg2,
    toolId: fetchId,
    durationMs: 860,
    result: "发布会日期 2026-10-21，许可证 Apache-2.0，上下文窗口 512k；页面未提及榜单名次。",
  };

  yield { type: "delegate_end", messageId: msg2, delegateId };

  yield* typeOut(
    msg2,
    `本周 3 条值得看：\n\n1. **[10-21] 开源模型 A 发布** — 512k 上下文、Apache-2.0，权重与模型卡同日在 GitHub 放出（来源：官方博客 · 一手）\n2. **[10-23] Agent 框架 B 1.4** — 新增子 Agent 并行委派与结构化输出契约，改动集中在调度层（来源：GitHub Release · 一手）\n3. **[10-19] 推理优化论文** — 报告称同硬件吞吐提升 1.7×，但未给端到端复现脚本，属单方声明（来源：arXiv · 准一手）\n\n**冲突**：模型 A 的参数量，模型卡写 32B，两家媒体写 30B。以模型卡为准，媒体数据未标注来源。\n\n**未证实**：社区传闻 A 下周开放 API 并降价，官方渠道无对应公告，已隔离到 unverified。`,
    6,
  );
  yield { type: "assistant_end", id: msg2 };

  const msg3 = uid("msg");
  yield { type: "phase", phase: "reviewing" };
  yield { type: "assistant_start", id: msg3 };
  yield* typeOut(
    msg3,
    `对照契约自查：7 段齐全；每条带 URL 与发布日期；参数量冲突已双列并以模型卡为准；榜单名次因无官方口径未写入。`,
  );
  yield { type: "assistant_end", id: msg3 };

  yield { type: "phase", phase: "result" };
  yield { type: "memory", item: memoryItem({ content: "关注方向：AI 模型发布 / Agent 框架", type: "semantic", key: "ai_watch_topic" }) };
  yield { type: "memory", item: memoryItem({ content: "2026-10 第 4 周 AI 动态简报：3 条，1 条冲突，1 条传闻", type: "episodic", confidence: 0.9 }) };
  yield { type: "done" };
}

/** 报告：委派 report-writer，读技能正文 */
async function* reportScript(input: string): AsyncGenerator<EngineEvent> {
  const msg1 = uid("msg");
  yield { type: "phase", phase: "planning" };
  yield { type: "assistant_start", id: msg1 };
  yield* typeOut(msg1, `写报告先定读者和结构。我先读 report-style 技能正文，再委派 report-writer 按 5 段契约产出。`);
  yield { type: "assistant_end", id: msg1 };

  const msg2 = uid("msg");
  yield { type: "phase", phase: "executing" };
  yield { type: "assistant_start", id: msg2 };

  const skillId = uid("tool");
  yield {
    type: "tool_start",
    messageId: msg2,
    tool: { id: skillId, name: "read_skill", args: 'skill_id="builtin/core/report-style/SKILL.md"', status: "running" },
  };
  await sleep(520);
  yield {
    type: "tool_end",
    messageId: msg2,
    toolId: skillId,
    durationMs: 480,
    result: "已载入正文：结构 5 段、语气规则、数据口径要求；资源 resources/outline.md 可按需分页读取。",
  };

  const delegateId = uid("dlg");
  yield {
    type: "delegate_start",
    messageId: msg2,
    delegate: {
      id: delegateId,
      agent: "report-writer",
      task: input.slice(0, 60) || "把已有材料整理成报告",
      tools: ["read_memory", "read_skill", "list_skills"],
      status: "running",
    },
  };
  await sleep(1400);
  yield { type: "delegate_end", messageId: msg2, delegateId };

  yield* typeOut(
    msg2,
    `报告已按 5 段契约产出：\n\n**摘要** — 三条结论，其中一条为推断，已在正文标注依据。\n**正文** — 按「背景 / 方法 / 发现」组织，单节不超过 300 字。\n**结论** — 编号 3 条，均可独立成立。\n**下一步** — 2 个待办，标明前置条件。\n\n材料缺口：缺少 9 月数据，正文中留了明确标记，没有补写。`,
    6,
  );
  yield { type: "assistant_end", id: msg2 };

  const msg3 = uid("msg");
  yield { type: "phase", phase: "reviewing" };
  yield { type: "assistant_start", id: msg3 };
  yield* typeOut(msg3, `自查：结构符合技能规范；数字均带口径；推断与事实已分离。9 月数据缺口已声明，未编造。`);
  yield { type: "assistant_end", id: msg3 };

  yield { type: "phase", phase: "result" };
  yield { type: "memory", item: memoryItem({ content: "用户偏好：报告按 5 段结构交付", type: "semantic", key: "report_structure" }) };
  yield { type: "done" };
}

/** 记忆写入：走 remember 工具 */
async function* memoryScript(input: string): AsyncGenerator<EngineEvent> {
  const msg1 = uid("msg");
  yield { type: "phase", phase: "planning" };
  yield { type: "assistant_start", id: msg1 };
  yield* typeOut(msg1, `这是长期偏好，不是一次性要求。我按语义记忆写入，并做冲突判定。`);
  yield { type: "assistant_end", id: msg1 };

  const msg2 = uid("msg");
  yield { type: "phase", phase: "executing" };
  yield { type: "assistant_start", id: msg2 };

  const toolId = uid("tool");
  yield {
    type: "tool_start",
    messageId: msg2,
    tool: {
      id: toolId,
      name: "remember",
      args: `content="${input.slice(0, 40)}" memory_type="semantic" key="output_format"`,
      status: "running",
    },
  };
  await sleep(600);
  yield {
    type: "tool_end",
    messageId: msg2,
    toolId,
    durationMs: 520,
    result: "写入 m_7f31c2 · 旧值 output_format=table 已标记失效（保留 1 条历史版本）",
  };

  yield* typeOut(msg2, `已记住，并让旧值失效——历史版本保留可追溯，当前生效的是这一条。`);
  yield { type: "assistant_end", id: msg2 };

  yield { type: "phase", phase: "result" };
  yield { type: "memory", item: memoryItem({ content: "用户偏好输出格式（新值）", key: "output_format", type: "semantic" }) };
  yield { type: "done" };
}

/** 默认：COLD 记忆检索后回答 */
async function* defaultScript(input: string): AsyncGenerator<EngineEvent> {
  const msg1 = uid("msg");
  yield { type: "phase", phase: "planning" };
  yield { type: "assistant_start", id: msg1 };
  yield* typeOut(msg1, `先看看有没有相关记忆，避免重复问你。`);
  yield { type: "assistant_end", id: msg1 };

  const msg2 = uid("msg");
  yield { type: "phase", phase: "executing" };
  yield { type: "assistant_start", id: msg2 };

  const toolId = uid("tool");
  yield {
    type: "tool_start",
    messageId: msg2,
    tool: { id: toolId, name: "read_memory", args: `query="${input.slice(0, 30)}" k=5`, status: "running" },
  };
  await sleep(700);
  yield {
    type: "tool_end",
    messageId: msg2,
    toolId,
    durationMs: 640,
    result: "命中 2 条：procedural「对比供应商先看交期」（0.71）、episodic「季度复盘按供应商分组」（0.58）",
  };

  yield* typeOut(
    msg2,
    `记忆里有相关经验：对比供应商时先看交期，再看价格与账期。我按这个顺序处理，需要的话可以展开成表格。\n\n（当前是演示脚本：这条回复由本地 mock 引擎生成，接上后端后走真实的 LangGraph 流式输出。）`,
    6,
  );
  yield { type: "assistant_end", id: msg2 };

  yield { type: "phase", phase: "result" };
  yield { type: "done" };
}

export function pickScript(input: string) {
  const text = input.toLowerCase();
  if (/(ai|人工智能|模型|论文|动态|新闻)/.test(text)) return aiNewsScript;
  if (/(报告|文档|整理成文|汇报)/.test(text)) return reportScript;
  if (/(记住|以后都|偏好|默认用)/.test(text)) return memoryScript;
  return defaultScript;
}

export async function* runTurn(input: string): AsyncGenerator<EngineEvent> {
  yield* pickScript(input)(input);
}

export function currentPhase(phase: Phase): Phase {
  return phase;
}
