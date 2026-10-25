import type { SessionItem } from "../lib/types";
import { IconMoon, IconPlus, IconSearch, IconSun } from "./Icons";

interface SidebarProps {
  sessions: SessionItem[];
  activeSession: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}

const PHASE_DOT: Record<string, string> = {
  planning: "planning",
  executing: "executing",
  reviewing: "reviewing",
  result: "result",
};

export default function Sidebar({
  sessions,
  activeSession,
  onSelect,
  onNew,
  theme,
  onToggleTheme,
}: SidebarProps) {
  return (
    <aside className="rail">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </span>
        <span className="brand-text">
          <strong>Harness</strong>
          <em>console</em>
        </span>
      </div>

      <button className="new-session" onClick={onNew}>
        <IconPlus width={16} height={16} />
        新建会话
      </button>

      <label className="search">
        <IconSearch width={15} height={15} />
        <input placeholder="搜索会话…" aria-label="搜索会话" />
        <kbd>⌘K</kbd>
      </label>

      <div className="rail-section">
        <span className="rail-label">最近</span>
        <ul className="session-list">
          {sessions.map((session) => (
            <li key={session.id}>
              <button
                className={`session ${activeSession === session.id ? "is-active" : ""}`}
                onClick={() => onSelect(session.id)}
              >
                <span className={`dot ${PHASE_DOT[session.phase] ?? "result"}`} />
                <span className="session-title">{session.title}</span>
                <span className="session-time">{session.updatedAt}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="rail-foot">
        <div className="runtime">
          <div className="runtime-row">
            <span className="k">model</span>
            <span className="v">deepseek-chat</span>
          </div>
          <div className="runtime-row">
            <span className="k">memory</span>
            <span className="v ok">warm · cold</span>
          </div>
          <div className="runtime-row">
            <span className="k">backend</span>
            <span className="v muted">mock stream</span>
          </div>
        </div>
        <button className="theme-toggle" onClick={onToggleTheme} aria-label="切换主题">
          {theme === "dark" ? (
            <>
              <IconSun width={15} height={15} /> 浅色
            </>
          ) : (
            <>
              <IconMoon width={15} height={15} /> 深色
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
