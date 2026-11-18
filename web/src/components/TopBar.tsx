import { useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { LayoutGrid, Moon, RefreshCw, Settings, Sun } from "lucide-react";
import { NavLink } from "react-router-dom";
import type { Health, RunState } from "../api";
import { applyTheme, currentTheme, runThemeTransition, type Theme } from "../theme";

interface Props {
  health: Health | null;
  progress: RunState | null;
  onRefresh: () => void;
}

export default function TopBar({ health, progress, onRefresh }: Props) {
  const running = Boolean(progress?.running);
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const pct = running && total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const count = health?.items ?? 0;
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

  const flipTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    // 换色和图标都要在同一帧里换掉，View Transition 抓到的「新页面」才是目标主题
    runThemeTransition(() => {
      applyTheme(next);
      flushSync(() => setTheme(next));
    });
  };

  // 「t」键换主题：键盘用户不必去点右上角
  useEffect(() => {
    const onTheme = () => flipTheme();
    window.addEventListener("onefeed:theme", onTheme);
    return () => window.removeEventListener("onefeed:theme", onTheme);
  });

  return (
    // 顶栏独立成一层转场元素：整页在飞，导航不能跟着抖
    <header
      data-vt="topbar"
      style={{ viewTransitionName: "of-topbar" }}
      className="sticky top-0 z-30 border-b border-line bg-paper/92 backdrop-blur"
    >
      <div className="relative mx-auto flex h-14 w-full max-w-[1180px] items-center gap-4 px-6">
        <NavLink to="/" className="flex items-baseline gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-solid text-[13px] font-semibold text-solid-fg">
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
          {/* 固定宽度占位：刷新与否都占同样宽度，按钮不会左右跳 */}
          <span
            aria-live="polite"
            className={
              "hidden w-10 text-right text-[11px] tabular-nums text-fade transition-opacity duration-200 md:inline-block " +
              (running ? "opacity-100" : "opacity-0")
            }
          >
            {done}/{total}
          </span>
          <button
            onClick={onRefresh}
            disabled={running}
            title="刷新全部平台"
            aria-label="刷新全部平台"
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-wash disabled:opacity-40"
          >
            <RefreshCw size={17} className={running ? "animate-spin" : ""} />
          </button>
          <button
            onClick={flipTheme}
            title={theme === "dark" ? "切换到亮色" : "切换到暗色"}
            aria-label={theme === "dark" ? "切换到亮色" : "切换到暗色"}
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-wash"
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <NavLink
            to="/market"
            title="插件市场"
            aria-label="插件市场"
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
            aria-label="设置"
            className={({ isActive }) =>
              "flex h-9 w-9 items-center justify-center rounded-full transition hover:bg-wash " +
              (isActive ? "text-ink" : "text-muted")
            }
          >
            <Settings size={17} />
          </NavLink>
        </div>
        {/* 进度条贴在页头下边缘：绝对定位，出现和消失都不推动页面 */}
        <span aria-hidden className="pointer-events-none absolute inset-x-0 -bottom-px h-[2px] bg-transparent">
          <span className="block h-full bg-solid transition-[width] duration-500" style={{ width: pct + "%" }} />
        </span>
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
