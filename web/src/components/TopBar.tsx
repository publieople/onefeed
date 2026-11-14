import { LayoutGrid, RefreshCw, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";
import type { Health, RunState } from "../api";

interface Props {
  health: Health | null;
  progress: RunState | null;
  onRefresh: () => void;
}

export default function TopBar({ health, progress, onRefresh }: Props) {
  const running = Boolean(progress?.running);
  const count = health?.items ?? 0;
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/92 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1180px] items-center gap-4 px-6">
        <NavLink to="/" className="flex items-baseline gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ink text-[13px] font-semibold text-white">
            O
          </span>
          <span className="text-[17px] font-semibold tracking-tight">OneFeed</span>
          <span className="hidden text-[11px] uppercase tracking-[0.16em] text-fade sm:inline">
            feed · {health?.plugins ?? 0} sources
          </span>
        </NavLink>
        <span className="ml-auto hidden text-[12px] text-fade md:inline">
          {count ? count + " 条 · 最近采集 " + timeOf(health?.platforms ?? []) : "还没有内容"}
        </span>
        <div className="ml-2 flex items-center gap-1">
          <button
            onClick={onRefresh}
            disabled={running}
            title="刷新六个平台"
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-wash disabled:opacity-40"
          >
            <RefreshCw size={17} className={running ? "animate-spin" : ""} />
          </button>
          <NavLink
            to="/market"
            title="插件市场"
            className={({ isActive }) =>
              "flex h-9 w-9 items-center justify-center rounded-full transition hover:bg-wash " +
              (isActive ? "text-ink" : "text-muted")
            }
          >
            <LayoutGrid size={17} />
          </NavLink>
          <NavLink
            to="/settings"
            title="设置"
            className={({ isActive }) =>
              "flex h-9 w-9 items-center justify-center rounded-full transition hover:bg-wash " +
              (isActive ? "text-ink" : "text-muted")
            }
          >
            <Settings size={17} />
          </NavLink>
        </div>
      </div>
    </header>
  );
}

function timeOf(platforms: { last_fetched_at: number }[]): string {
  const newest = Math.max(0, ...platforms.map((p) => p.last_fetched_at));
  if (!newest) return "—";
  const d = new Date(newest * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return hh + ":" + mm;
}
