import { useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { LayoutGrid, Moon, RefreshCw, Settings, Sun } from "lucide-react";
import { NavLink } from "react-router-dom";
import type { Health, RunState } from "../api";
import { applyTheme, currentTheme, runThemeTransition, type Theme } from "../theme";
import CollectPill from "./CollectPill";
import RefreshProgress from "./RefreshProgress";

interface Props {
  health: Health | null;
  progress: RunState | null;
  onRefresh: () => void;
  /** 「重试失败」要把平台列表递回去 */
  onRetry: (platforms: string[]) => void;
}

export default function TopBar({ health, progress, onRefresh, onRetry }: Props) {
  const running = Boolean(progress?.running);
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  // 正在抓哪个平台、抓完了几个：只转圈看不出「它还在动」还是「卡住了」
  const runningRow = Object.entries(progress?.plugins ?? {}).find(([, p]) => p.status === "running");
  const runningLabel = runningRow ? runningRow[1].label || runningRow[0] : "";
  const refreshTitle = running
    ? (runningLabel ? "正在抓 " + runningLabel + "，" : "正在抓取，") + "已完成 " + done + "/" + total
    : "刷新全部平台";

  // 运行中不再把按钮禁用掉：点了没反应比转圈更糟。
  // 进度就贴在按钮左边，所以不必再把人送到别处 —— 把进度件重新亮一下就行。
  const [hint, setHint] = useState(0);
  const clickRefresh = () => {
    if (!running) {
      onRefresh();
      return;
    }
    setHint((n) => n + 1);
  };

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
    // 依赖 theme：flipTheme 闭包里读它，但它每帧都会新建——这里只认 theme，
    // 否则每次渲染都解绑重绑一次，滚动时白白烧主线程。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  return (
    // 顶栏独立成一层转场元素：整页在飞，导航不能跟着抖
    <header
      data-vt="topbar"
      style={{ viewTransitionName: "of-topbar" }}
      className="sticky top-0 z-30 border-b border-line bg-paper"
    >
      {/* 通栏：品牌贴左缘、操作贴右缘，和下面两栏同一条边线对齐 */}
      <div className="relative flex h-14 w-full items-center gap-2 px-3 sm:gap-4 sm:px-6">
        <NavLink to="/" className="flex shrink-0 items-baseline gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-solid text-[13px] font-semibold text-solid-fg">
            O
          </span>
          <span className="hidden text-[17px] font-semibold tracking-tight min-[420px]:inline">OneFeed</span>
          <span className="hidden text-[11px] uppercase tracking-[0.16em] text-fade sm:inline">
            feed · {health?.plugins ?? 0} sources
          </span>
        </NavLink>
        {/* 两条内容通道的切换：信息流是平台推荐，关注是「我关注的人」。 */}
        <nav aria-label="内容视图" className="ml-0 flex shrink-0 items-center rounded-full border border-line bg-wash/40 p-0.5 sm:ml-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              "flex h-7 items-center whitespace-nowrap rounded-full px-2.5 text-[12px] transition " +
              (isActive ? "bg-paper text-ink shadow-sm" : "text-muted hover:text-ink")
            }
          >
            信息流
          </NavLink>
          <NavLink
            to="/following"
            className={({ isActive }) =>
              "flex h-7 items-center whitespace-nowrap rounded-full px-2.5 text-[12px] transition " +
              (isActive ? "bg-paper text-ink shadow-sm" : "text-muted hover:text-ink")
            }
          >
            关注
          </NavLink>
        </nav>
        {/* 右组是一排同规格的件：刷新（进度从它左边长出来）→ 采集情况 → 主题 / 市场 / 设置。
            采集那件以前是一行裸文本，宽度随字数跳，现在和图标按钮同高同位。 */}
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1">
          <div className="relative flex items-center">
            <RefreshProgress className="max-sm:hidden" progress={progress} hint={hint} onRetry={onRetry} />
            <button
              onClick={clickRefresh}
              title={refreshTitle}
              aria-label={refreshTitle}
              className="flex hit-44 h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-wash"
            >
              <RefreshCw size={17} className={running ? "animate-spin" : ""} />
            </button>
          </div>
          <div className="hidden sm:flex">
            <CollectPill health={health} onRetry={onRetry} />
          </div>
          <button
            onClick={flipTheme}
            title={theme === "dark" ? "切换到亮色" : "切换到暗色"}
            aria-label={theme === "dark" ? "切换到亮色" : "切换到暗色"}
            className="flex hit-44 h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-wash"
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <NavLink
            to="/market"
            title="插件市场"
            aria-label="插件市场"
            className={({ isActive }) =>
              "flex hit-44 h-9 w-9 items-center justify-center rounded-full transition hover:bg-wash " +
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
              "flex hit-44 h-9 w-9 items-center justify-center rounded-full transition hover:bg-wash " +
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
