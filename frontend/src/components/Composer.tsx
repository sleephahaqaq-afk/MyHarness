import { useEffect, useRef, useState } from "react";
import { IconSend } from "./Icons";

const QUICK = [
  { label: "最近一周 AI 动态", text: "帮我看看最近一周 AI 领域有什么新的动态" },
  { label: "写份季度报告", text: "把刚才的结论写一份季度采购报告" },
  { label: "以后都用表格", text: "以后默认都用表格输出" },
  { label: "对比三家供应商", text: "对比三家供应商的供货能力" },
];

export default function Composer({
  onSend,
  busy,
}: {
  onSend: (text: string) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState("");
  const areaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 168)}px`;
  }, [value]);

  const submit = () => {
    if (!value.trim() || busy) return;
    onSend(value);
    setValue("");
  };

  return (
    <div className="composer">
      <div className="composer-card">
        <textarea
          ref={areaRef}
          value={value}
          rows={1}
          placeholder="问我任何事 —— 需要外部信息我会委派子 Agent，长期偏好我会记住。"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <button className="send" onClick={submit} disabled={busy || !value.trim()} aria-label="发送">
          {busy ? <span className="sending" /> : <IconSend width={18} height={18} />}
        </button>
      </div>

      <div className="composer-foot">
        <div className="quick">
          {QUICK.map((item) => (
            <button
              key={item.label}
              className="chip quick-chip"
              disabled={busy}
              onClick={() => onSend(item.text)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="hint">Enter 发送 · Shift+Enter 换行</span>
      </div>
    </div>
  );
}
