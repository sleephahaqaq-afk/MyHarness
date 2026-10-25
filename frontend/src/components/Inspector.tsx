import type { MemoryItem, SkillItem, SubAgentItem } from "../lib/types";
import { IconAgents, IconMemory, IconSkill } from "./Icons";

export type InspectorTab = "memory" | "skills" | "subagents";

const TABS: { key: InspectorTab; label: string; icon: typeof IconMemory }[] = [
  { key: "memory", label: "记忆", icon: IconMemory },
  { key: "skills", label: "技能", icon: IconSkill },
  { key: "subagents", label: "子 Agent", icon: IconAgents },
];

const TYPE_LABEL: Record<string, string> = {
  semantic: "语义",
  episodic: "情节",
  procedural: "程序",
};

function Confidence({ value }: { value: number }) {
  return (
    <span className="conf" title={`confidence ${value.toFixed(2)}`}>
      <i style={{ width: `${Math.round(value * 100)}%` }} />
    </span>
  );
}

function MemoryPanel({ memory }: { memory: MemoryItem[] }) {
  const warm = memory.filter((item) => item.tier === "warm");
  const cold = memory.filter((item) => item.tier === "cold");
  const prefs = warm.filter((item) => item.type === "semantic");
  const episodes = warm.filter((item) => item.type !== "semantic");

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>WARM</h3>
        <span className="panel-note">每次模型调用前注入</span>
      </div>

      <div className="pref-grid">
        {prefs.length === 0 && <p className="empty">暂无偏好</p>}
        {prefs.map((item) => (
          <div key={item.id} className="pref">
            <span className="pref-key">{item.key ?? item.type}</span>
            <span className="pref-val">{item.content}</span>
            <Confidence value={item.confidence} />
          </div>
        ))}
      </div>

      <ul className="memory-list">
        {episodes.map((item) => (
          <li key={item.id}>
            <span className="mem-date">{item.createdAt.slice(5)}</span>
            <span className="mem-text">{item.content}</span>
          </li>
        ))}
      </ul>

      <div className="panel-head second">
        <h3>COLD</h3>
        <span className="panel-note">按需 read_memory 检索</span>
      </div>
      <ul className="memory-list cold">
        {cold.map((item) => (
          <li key={item.id}>
            <span className={`mem-type ${item.type}`}>{TYPE_LABEL[item.type]}</span>
            <span className="mem-text">{item.content}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SkillPanel({ skills }: { skills: SkillItem[] }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>技能目录</h3>
        <span className="panel-note">只注入元数据，正文按需读取</span>
      </div>
      <ul className="card-list">
        {skills.length === 0 && <li className="empty">暂无技能</li>}
        {skills.map((skill) => (
          <li key={skill.id} className="mini-card">
            <div className="mini-head">
              <strong>{skill.name}</strong>
              <span className="tag">{skill.group}</span>
            </div>
            <p>{skill.description}</p>
            <code className="mini-path">{skill.id}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SubAgentPanel({ subagents }: { subagents: SubAgentItem[] }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>子 Agent</h3>
        <span className="panel-note">YAML 声明式，工具按名匹配</span>
      </div>
      <ul className="card-list">
        {subagents.length === 0 && <li className="empty">暂无子 Agent</li>}
        {subagents.map((agent) => (
          <li key={agent.name} className="mini-card">
            <div className="mini-head">
              <strong>{agent.name}</strong>
              <span className="tag">{agent.sections.length} 段契约</span>
            </div>
            <p>{agent.description}</p>
            <div className="chips">
              {agent.tools.map((tool) => (
                <span key={tool} className="chip mono">
                  {tool}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Inspector({
  tab,
  onTab,
  memory,
  skills,
  subagents,
  error,
}: {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  memory: MemoryItem[];
  skills: SkillItem[];
  subagents: SubAgentItem[];
  error?: string | null;
}) {
  const counts: Record<InspectorTab, number> = {
    memory: memory.length,
    skills: skills.length,
    subagents: subagents.length,
  };

  return (
    <aside className="inspector">
      <nav className="tabs">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={`tab ${tab === key ? "is-active" : ""}`}
            onClick={() => onTab(key)}
          >
            <Icon width={15} height={15} />
            {label}
            <span className="tab-count">{counts[key]}</span>
          </button>
        ))}
      </nav>

      <div className="inspector-body">
        {error && <p className="panel-error">后端未就绪：{error}</p>}
        {tab === "memory" && <MemoryPanel memory={memory} />}
        {tab === "skills" && <SkillPanel skills={skills} />}
        {tab === "subagents" && <SubAgentPanel subagents={subagents} />}
      </div>
    </aside>
  );
}
