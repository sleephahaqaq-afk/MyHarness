import { Fragment, useState } from "react";
import type { DelegateCall, Message, ToolCall } from "../lib/types";
import { IconAgents, IconCheck, IconWrench } from "./Icons";

/** 极简富文本：段落 / 列表 / **粗体** / 换行（不引 markdown 库） */
function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/).filter((block) => block.trim().length > 0);
  return (
    <>
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        const listLines = lines.filter((line) => /^\s*(-|\d+\.)\s+/.test(line));
        if (listLines.length === lines.length && lines.length > 0) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={index} className="rich-list">
              {lines.map((line, i) => (
                <li key={i}>{inline(line.replace(/^\s*(-|\d+\.)\s+/, ""))}</li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={index}>
            {lines.map((line, i) => (
              <Fragment key={i}>
                {i > 0 && <br />}
                {inline(line)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}

function ToolCard({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false);
  const done = tool.status === "done";

  return (
    <div className={`tool-card ${tool.status}`}>
      <button className="tool-head" onClick={() => setOpen((prev) => !prev)}>
        <span className="tool-icon">
          <IconWrench width={13} height={13} />
        </span>
        <span className="tool-name">{tool.name}</span>
        <code className="tool-args">{tool.args}</code>
        <span className="tool-meta">
          {done ? `${tool.durationMs ?? 0} ms` : "running"}
          <span className={`status-pip ${tool.status}`} />
        </span>
      </button>
      {open && tool.result && <pre className="tool-result">{tool.result}</pre>}
    </div>
  );
}

function DelegateCard({ delegate }: { delegate: DelegateCall }) {
  return (
    <div className={`delegate-card ${delegate.status}`}>
      <div className="delegate-head">
        <IconAgents width={14} height={14} />
        <span className="delegate-label">delegated</span>
        <strong>{delegate.agent}</strong>
        <span className="delegate-status">
          {delegate.status === "running" ? "执行中" : "已返回"}
          {delegate.status === "done" && <IconCheck width={12} height={12} />}
        </span>
      </div>
      <p className="delegate-task">{delegate.task}</p>
      <div className="delegate-tools">
        {delegate.tools.map((tool) => (
          <span key={tool} className="chip mono">
            {tool}
          </span>
        ))}
      </div>
    </div>
  );
}

function MessageRow({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="msg-row user">
        <div className="bubble user">{message.content}</div>
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="msg-row">
        <div className="bubble system">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="msg-row assistant">
      <span className="avatar" aria-hidden="true">
        H
      </span>
      <div className="msg-body">
        {message.delegate && <DelegateCard delegate={message.delegate} />}
        {message.tools && message.tools.length > 0 && (
          <div className="tool-stack">
            {message.tools.map((tool) => (
              <ToolCard key={tool.id} tool={tool} />
            ))}
          </div>
        )}
        {message.content && (
          <div className="bubble assistant">
            <RichText text={message.content} />
            {message.streaming && <span className="caret" />}
          </div>
        )}
        {message.streaming && !message.content && (
          <div className="thinking">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>
    </div>
  );
}

export default function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div className="messages">
      {messages.map((message) => (
        <MessageRow key={message.id} message={message} />
      ))}
    </div>
  );
}
