export type Phase = "planning" | "executing" | "reviewing" | "result";

export type MessageRole = "user" | "assistant" | "system";

export interface ToolCall {
  id: string;
  name: string;
  args: string;
  status: "running" | "done" | "error";
  result?: string;
  durationMs?: number;
}

export interface DelegateCall {
  id: string;
  agent: string;
  task: string;
  tools: string[];
  status: "running" | "done";
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  phase?: Phase;
  tools?: ToolCall[];
  delegate?: DelegateCall;
  streaming?: boolean;
  createdAt: number;
}

export interface MemoryItem {
  id: string;
  tier: "warm" | "cold";
  type: "semantic" | "episodic" | "procedural";
  key?: string;
  content: string;
  confidence: number;
  createdAt: string;
}

export interface SkillItem {
  id: string;
  name: string;
  description: string;
  group: string;
}

export interface SubAgentItem {
  name: string;
  description: string;
  tools: string[];
  sections: string[];
}

export interface SessionItem {
  id: string;
  title: string;
  phase: Phase;
  updatedAt: string;
  active?: boolean;
}

export type EngineEvent =
  | { type: "phase"; phase: Phase }
  | { type: "assistant_start"; id: string }
  | { type: "delta"; id: string; text: string }
  | { type: "assistant_end"; id: string }
  | { type: "tool_start"; messageId: string; tool: ToolCall }
  | { type: "tool_end"; messageId: string; toolId: string; result: string; durationMs: number }
  | { type: "delegate_start"; messageId: string; delegate: DelegateCall }
  | { type: "delegate_end"; messageId: string; delegateId: string }
  | { type: "memory"; item: MemoryItem }
  | { type: "system"; text: string }
  | { type: "done" };
