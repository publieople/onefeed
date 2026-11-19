import { useEffect, type ReactNode } from "react";
import AgentSidebar from "../agent/AgentSidebar";
import { useAgentActions, useAgentSurface } from "../agent/AgentProvider";
import type { Health, RunState } from "../api";
import RightRail from "../components/RightRail";
import TopBar from "../components/TopBar";
import { popScope, pushScope, useHotkeys } from "../motion/useHotkeys";
import { useShell } from "./useShell";

/**
 * 外壳：左 Agent 工作台 / 中内容 / 右槽位。
 *
 * 左栏一直待在栅格里（1440 起 288、1024 起 64 图标轨），右栏只在 1800 起钉住，
 * 往下是抽屉 —— 因为 1440 段再塞 320 进去，中间的内容列就只剩 800 多，
 * 三列卡片会挤成一条缝。内容列宽度稳定优先于视觉对称。
 */
export default function Shell({
  health,
  progress,
  onRefresh,
  onHelp,
  children,
}: {
  health: Health | null;
  progress: RunState | null;
  onRefresh: () => void;
  onHelp: () => void;
  children: ReactNode;
}) {
  const shell = useShell();
  const { mode, onItemPage } = useAgentSurface();
  const { close } = useAgentActions();

  const pinned = shell.right === "pinned";
  const rail = mode === "rail";
  const drawerOpen = !pinned && (shell.rightOpen || rail);
  // 1280 以上抽屉把内容让开（瞬时让位，不逐帧动画）：340 盖在 1180 的内容列上，
  // 会切掉右边一整列卡片，看起来像页面坏了。窄屏没地方让，只能盖上去。
  const pushRight = drawerOpen && shell.width >= 1280;

  // [ ] 开合两侧；打开时压一层 dialog 作用域，Esc 先关最上面那层
  useHotkeys("global", { "[": shell.toggleLeft, "]": shell.toggleRight });

  useEffect(() => {
    if (!shell.leftDrawer) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [shell.leftDrawer]);
  useHotkeys("dialog", { escape: () => shell.setLeftDrawer(false) }, shell.leftDrawer);

  useEffect(() => {
    if (!drawerOpen) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [drawerOpen]);
  useHotkeys(
    "dialog",
    { escape: () => (rail ? close() : shell.setRightOpen(false)) },
    drawerOpen,
  );

  // 左栏钉住之后浮层没有意义，别留在那儿
  useEffect(() => {
    if (shell.left === "full" && shell.leftDrawer) shell.setLeftDrawer(false);
  }, [shell.left, shell.leftDrawer, shell.setLeftDrawer]);

  const dismissRail = () => {
    if (rail) close();
    shell.setRightOpen(false);
  };

  return (
    <div className="min-h-screen bg-paper">
      {/* 键盘用户第一个 Tab 就能跳过顶栏直达内容 */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-full focus:bg-solid focus:px-4 focus:py-2 focus:text-[13px] focus:text-solid-fg"
      >
        跳到内容
      </a>
      <TopBar health={health} progress={progress} onRefresh={onRefresh} />

      <div
        className="mx-auto flex w-full max-w-[1820px] items-start justify-center gap-5 px-5"
        style={pushRight ? { paddingRight: 364 } : undefined}
      >
        {shell.left === "full" ? (
          <AgentSidebar onCollapse={shell.toggleLeft} onHelp={onHelp} />
        ) : null}
        {shell.left === "rail" ? (
          <AgentSidebar collapsed onExpand={() => shell.setLeftDrawer(true)} onHelp={onHelp} />
        ) : null}

        <main id="main" tabIndex={-1} className="w-full min-w-0 max-w-[1180px] px-6 outline-none">
          {children}
        </main>

        {pinned && (shell.rightOpen || rail) ? (
          <RightRail
            className="sticky top-[76px] h-[calc(100vh-96px)] min-h-[420px] w-[320px] shrink-0"
            defaultTab={onItemPage ? "ai" : "saved"}
            onClose={dismissRail}
          />
        ) : null}
      </div>

      {shell.leftDrawer ? (
        <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label="Agent 工作台">
          <button
            className="absolute inset-0 bg-solid/20"
            onClick={() => shell.setLeftDrawer(false)}
            aria-label="收起 Agent 工作台"
          />
          <div className="relative z-10 h-full p-2">
            <AgentSidebar
              drawer
              onCollapse={() => shell.setLeftDrawer(false)}
              onNavigate={() => shell.setLeftDrawer(false)}
              onHelp={onHelp}
            />
          </div>
        </div>
      ) : null}

      {drawerOpen ? (
        // 不做遮罩：详情页右栏要能跟内容并排用，蒙一层会把点击吞掉
        <div className="fixed inset-y-0 right-0 z-40 flex w-[340px] max-w-[92vw] flex-col p-3">
          <RightRail
            className="h-full"
            defaultTab={onItemPage ? "ai" : "saved"}
            onClose={dismissRail}
          />
        </div>
      ) : null}
    </div>
  );
}
