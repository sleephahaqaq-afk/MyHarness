import type { MemoryItem, SessionItem, SkillItem, SubAgentItem } from "../lib/types";

export const SESSIONS: SessionItem[] = [
  { id: "s-1", title: "最近一周 AI 领域动态", phase: "result", updatedAt: "16:12", active: true },
  { id: "s-2", title: "供应商交期对比报告", phase: "reviewing", updatedAt: "14:38" },
  { id: "s-3", title: "把输出统一成表格", phase: "result", updatedAt: "11:05" },
  { id: "s-4", title: "调研 Agent 记忆方案", phase: "executing", updatedAt: "昨天" },
  { id: "s-5", title: "整理季度采购复盘", phase: "result", updatedAt: "10-23" },
];

export const SKILLS: SkillItem[] = [
  {
    id: "builtin/research/ai-news-digest/SKILL.md",
    name: "ai-news-digest",
    description: "AI 资讯的来源分级、时间判定与去重规则",
    group: "research",
  },
  {
    id: "builtin/core/report-style/SKILL.md",
    name: "report-style",
    description: "报告/文档输出的结构与语气规范",
    group: "core",
  },
  {
    id: "builtin/core/memory-hygiene/SKILL.md",
    name: "memory-hygiene",
    description: "什么该写进长期记忆、什么不该写",
    group: "core",
  },
];

export const SUBAGENTS: SubAgentItem[] = [
  {
    name: "ai-news-scout",
    description: "AI 情报侦察员：检索并交叉核对最新动态，输出带来源与日期的简报",
    tools: ["web_search", "web_fetch", "read_skill"],
    sections: ["scan_window", "top_items", "conflicts", "unverified", "sources"],
  },
  {
    name: "research-analyst",
    description: "资料研究专员：检索与交叉验证，输出带来源的结构化结论",
    tools: ["web_search", "web_fetch", "read_memory"],
    sections: ["question", "sources", "findings", "conflicts"],
  },
  {
    name: "report-writer",
    description: "报告撰写专员：把已有材料整理成结构清晰的成文产物",
    tools: ["read_memory", "read_skill", "list_skills"],
    sections: ["title", "summary", "body", "conclusions"],
  },
];

export const INITIAL_MEMORY: MemoryItem[] = [
  {
    id: "m-1",
    tier: "warm",
    type: "semantic",
    key: "output_format",
    content: "markdown",
    confidence: 0.8,
    createdAt: "2026-10-20",
  },
  {
    id: "m-2",
    tier: "warm",
    type: "semantic",
    key: "language",
    content: "zh",
    confidence: 0.8,
    createdAt: "2026-10-18",
  },
  {
    id: "m-3",
    tier: "warm",
    type: "episodic",
    content: "整理季度采购复盘，结论按供应商分组",
    confidence: 0.9,
    createdAt: "2026-10-23",
  },
  {
    id: "m-4",
    tier: "cold",
    type: "procedural",
    content: "对比供应商时先看交期，再看价格与账期",
    confidence: 0.7,
    createdAt: "2026-09-30",
  },
  {
    id: "m-5",
    tier: "cold",
    type: "episodic",
    content: "调研 Agent 记忆分层方案，L1/L2/L3 结论待复核",
    confidence: 0.9,
    createdAt: "2026-09-12",
  },
];

export const PHASE_LABEL: Record<string, string> = {
  planning: "Planning",
  executing: "Executing",
  reviewing: "Review",
  result: "Result",
};
