import type { RunState } from "../api";
import { platform } from "../platform";

export default function ProgressBar({ state }: { state: RunState }) {
  const total = Math.max(1, state.total);
  const pct = Math.min(100, Math.round((state.done / total) * 100));
  const current = Object.entries(state.plugins).find(([, v]) => v.status === "running");
  const label = current ? platform(current[0]).label : "收尾";
  return (
    <div className="border-b border-line bg-wash/60">
      <div className="mx-auto w-full max-w-[1180px] px-6 py-2">
        <div className="flex items-center justify-between text-[12px] text-muted">
          <span>
            正在刷新 {state.done}/{state.total} · {label}
          </span>
          <span>{pct}%</span>
        </div>
        <div className="mt-1.5 h-[2px] w-full overflow-hidden rounded bg-line">
          <div className="h-full bg-ink transition-all duration-500" style={{ width: pct + "%" }} />
        </div>
      </div>
    </div>
  );
}
