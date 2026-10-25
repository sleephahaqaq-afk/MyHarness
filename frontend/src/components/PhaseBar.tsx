import type { Phase } from "../lib/types";

const STEPS: { key: Phase; label: string; hint: string }[] = [
  { key: "planning", label: "Plan", hint: "拆解目标" },
  { key: "executing", label: "Execute", hint: "调工具 / 委派" },
  { key: "reviewing", label: "Review", hint: "对照检查项" },
  { key: "result", label: "Result", hint: "交付结论" },
];

export default function PhaseBar({ phase, busy }: { phase: Phase; busy: boolean }) {
  const current = STEPS.findIndex((step) => step.key === phase);

  return (
    <div className="phase-bar" role="status" aria-label={`当前阶段 ${phase}`}>
      {STEPS.map((step, index) => {
        const state =
          index < current ? "done" : index === current ? (busy ? "active" : "current") : "todo";
        return (
          <span key={step.key} className={`phase-step ${state}`} title={step.hint}>
            <i className="phase-dot" />
            {step.label}
          </span>
        );
      })}
    </div>
  );
}
