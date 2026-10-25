import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import PhaseBar from "./components/PhaseBar";
import MessageList from "./components/MessageList";
import Composer from "./components/Composer";
import Inspector, { type InspectorTab } from "./components/Inspector";
import { INITIAL_MEMORY, SESSIONS, SKILLS, SUBAGENTS } from "./data/seed";
import {
  USE_MOCK,
  fetchMemory,
  fetchSkills,
  fetchSubagents,
  streamChat,
} from "./lib/api";
import type { EngineEvent, MemoryItem, Message, Phase, SkillItem, SubAgentItem } from "./lib/types";

const SESSION_ID = "demo-session";

const GREETING: Message = {
  id: "greeting",
  role: "assistant",
  content:
    "这是 MyHarness 基座的控制台。中间的命令我按 Planning → Executing → Review → Result 四阶段处理；需要外部信息会委派给子 Agent，长期偏好会写进记忆。\n\n试试下面的快捷入口，或者直接问我。",
  phase: "planning",
  tools: [],
  createdAt: Date.now(),
};

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [messages, setMessages] = useState<Message[]>([GREETING]);
  const [phase, setPhase] = useState<Phase>("planning");
  // mock 模式用种子数据；真实模式从后端拉，初始为空而不是假数据
  const [memory, setMemory] = useState<MemoryItem[]>(USE_MOCK ? INITIAL_MEMORY : []);
  const [skills, setSkills] = useState<SkillItem[]>(USE_MOCK ? SKILLS : []);
  const [subagents, setSubagents] = useState<SubAgentItem[]>(USE_MOCK ? SUBAGENTS : []);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<InspectorTab>("memory");
  const [activeSession, setActiveSession] = useState(SESSIONS[0].id);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    document.body.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const refreshMemory = useCallback(async () => {
    try {
      setMemory(await fetchMemory());
      setLoadError(null);
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    if (USE_MOCK) return;
    let cancelled = false;
    (async () => {
      try {
        const [nextSkills, nextSubagents] = await Promise.all([fetchSkills(), fetchSubagents()]);
        if (cancelled) return;
        setSkills(nextSkills);
        setSubagents(nextSubagents);
        await refreshMemory();
      } catch (error) {
        if (!cancelled) setLoadError((error as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshMemory]);

  const applyEvent = useCallback((event: EngineEvent) => {
    switch (event.type) {
      case "phase":
        setPhase(event.phase);
        break;
      case "assistant_start":
        setMessages((prev) => [
          ...prev,
          {
            id: event.id,
            role: "assistant",
            content: "",
            tools: [],
            streaming: true,
            createdAt: Date.now(),
          },
        ]);
        break;
      case "delta":
        setMessages((prev) =>
          prev.map((item) =>
            item.id === event.id ? { ...item, content: item.content + event.text } : item,
          ),
        );
        break;
      case "assistant_end":
        setMessages((prev) =>
          prev.map((item) => (item.id === event.id ? { ...item, streaming: false } : item)),
        );
        break;
      case "tool_start":
        setMessages((prev) =>
          prev.map((item) =>
            item.id === event.messageId
              ? { ...item, tools: [...(item.tools ?? []), event.tool] }
              : item,
          ),
        );
        break;
      case "tool_end":
        setMessages((prev) =>
          prev.map((item) =>
            item.id === event.messageId
              ? {
                  ...item,
                  tools: (item.tools ?? []).map((tool) =>
                    tool.id === event.toolId
                      ? {
                          ...tool,
                          status: "done" as const,
                          result: event.result,
                          durationMs: event.durationMs,
                        }
                      : tool,
                  ),
                }
              : item,
          ),
        );
        break;
      case "delegate_start":
        setMessages((prev) =>
          prev.map((item) =>
            item.id === event.messageId ? { ...item, delegate: event.delegate } : item,
          ),
        );
        break;
      case "delegate_end":
        setMessages((prev) =>
          prev.map((item) =>
            item.id === event.messageId && item.delegate
              ? { ...item, delegate: { ...item.delegate, status: "done" as const } }
              : item,
          ),
        );
        break;
      case "memory":
        setMemory((prev) => {
          const next = prev.filter(
            (item) => !(item.key && item.key === event.item.key && item.tier === "warm"),
          );
          return [event.item, ...next];
        });
        break;
      case "system":
        setMessages((prev) => [
          ...prev,
          {
            id: `sys-${Date.now()}`,
            role: "system",
            content: event.text,
            createdAt: Date.now(),
          },
        ]);
        break;
      case "done":
        break;
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;

      setBusy(true);
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: "user", content: trimmed, createdAt: Date.now() },
      ]);

      try {
        for await (const event of streamChat(trimmed, SESSION_ID)) {
          applyEvent(event);
        }
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "system",
            content: `请求失败：${(error as Error).message}`,
            createdAt: Date.now(),
          },
        ]);
      } finally {
        setBusy(false);
        // 一轮结束后记忆可能新增/失效，重新拉一次（mock 模式自己发 memory 事件，不用拉）
        if (!USE_MOCK) void refreshMemory();
      }
    },
    [applyEvent, busy, refreshMemory],
  );

  const newSession = useCallback(() => {
    if (busy) return;
    setMessages([{ ...GREETING, id: `greeting-${Date.now()}`, createdAt: Date.now() }]);
    setPhase("planning");
    setActiveSession("");
  }, [busy]);

  return (
    <div className="shell">
      <Sidebar
        sessions={SESSIONS}
        activeSession={activeSession}
        onSelect={setActiveSession}
        onNew={newSession}
        theme={theme}
        onToggleTheme={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
      />

      <main className="stage">
        <header className="stage-head">
          <div className="stage-head-row">
            <span className="eyebrow">MyHarness · agent base</span>
            <PhaseBar phase={phase} busy={busy} />
          </div>
          <h1>
            Harness <span className="hl">Console</span>
          </h1>
          <p className="stage-sub">
            middlewares · memory · skills · subagents —— 四层基座的可视化工作台
          </p>
          <div className="dotfield" aria-hidden="true" />
        </header>

        <div className="thread">
          <MessageList messages={messages} />
          <div ref={bottomRef} />
        </div>

        <Composer onSend={send} busy={busy} />
      </main>

      <Inspector
        tab={tab}
        onTab={setTab}
        memory={memory}
        skills={skills}
        subagents={subagents}
        error={loadError}
      />
    </div>
  );
}
