import type { EngineEvent, MemoryItem, SkillItem, SubAgentItem } from "./types";
import { runTurn } from "./mockEngine";

/**
 * 后端接入点。
 *
 * 默认走真实后端（`python scripts/serve.py`）；要纯前端演示时显式打开 mock：
 *
 *     VITE_USE_MOCK=1 npm run dev
 *
 * 不做「连不上就悄悄退回 mock」——那种隐式回退会让你误以为后端通了。
 * 后端没起时，请求失败会抛错，UI 会渲染成一张红色错误卡。
 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "1";

/** 与后端 /api/* 的 user_id 保持一致（演示用单用户）。 */
export const USER_ID = "demo";

/** 后端 item 形状；invalidated 的历史版本 valid=false。 */
interface MemoryItemWire extends MemoryItem {
  valid: boolean;
}

interface MemoryResponse {
  user_id: string;
  preferences: Record<string, string>;
  warm_brief: string;
  stats: Record<string, number>;
  items: MemoryItemWire[];
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${path} 返回 ${response.status}`);
  }
  return (await response.json()) as T;
}

/** 只返回当前有效的记忆；失效的历史版本由 stats 里的 `*_history` 体现。 */
export async function fetchMemory(userId = USER_ID): Promise<MemoryItem[]> {
  const data = await getJson<MemoryResponse>(`/api/memory?user_id=${encodeURIComponent(userId)}`);
  return data.items.filter((item) => item.valid);
}

export async function fetchSkills(): Promise<SkillItem[]> {
  const rows = await getJson<{ id: string; name: string; description: string }[]>("/api/skills");
  return rows.map((row) => ({
    ...row,
    // id 形如 builtin/core/report-style/SKILL.md，第二段就是分组
    group: row.id.split("/")[1] ?? "builtin",
  }));
}

export function fetchSubagents(): Promise<SubAgentItem[]> {
  return getJson<SubAgentItem[]>("/api/subagents");
}

async function* streamFromBackend(input: string, sessionId: string): AsyncGenerator<EngineEvent> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: input, user_id: USER_ID, session_id: sessionId }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`后端返回 ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((item) => item.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === "[DONE]") continue;
      try {
        yield JSON.parse(payload) as EngineEvent;
      } catch {
        // 忽略无法解析的心跳帧
      }
    }
  }
}

export async function* streamChat(input: string, sessionId: string): AsyncGenerator<EngineEvent> {
  if (USE_MOCK) {
    yield* runTurn(input);
    return;
  }
  yield* streamFromBackend(input, sessionId);
}
