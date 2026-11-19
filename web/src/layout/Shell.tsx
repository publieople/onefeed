import { useEffect, type ReactNode } from "react";
import AgentSidebar from "../agent/AgentSidebar";
import { useAgentActions, useAgentSurface } from "../agent/AgentProvider";
import type { Health, RunState } from "../api";
import RightRail from "../components/RightRail";
import TopBar from "../components/TopBar";
import { popScope, pushScope, useHotkeys } from "../motion/useHotkeys";
import { usePresence } from "../motion/usePresence";
import { useShell } from "./useShell";

/** 左栏两档宽度：展开 288、图标轨 64。写常量是因为宽度要拿去过渡，不能再靠 class 切换。 */
const LEFT_W_FULL = 288;
const LEFT_W_RAIL = 64;

/**
 * 外壳：左 Agent 工作台 / 中内容 / 右槽位。
 *
 * 左栏一直待在栅格里（1440 起 288、1024 起 64 图标轨），右栏只在 1800 起钉住，
 * 往下是抽屉 —— 因为 1440 段再塞 320 进去，中间的内容列就只剩 800 多，
 * 三列卡片会挤成一条缝。内容列宽度稳定优先于视觉对称。
 *
 * 左栏展开 = 这一列从 64 变宽成 288，内容列被 flex 挤窄；
 * 不再有 fixed 的全屏浮层（那种会盖住整页，破坏沉浸感）。
 *
 * 收放都要有过渡：宽度走外层容器的 width 过渡（两段分支共用同一层，
 * 所以换分支时那一列还在，能连续变宽变窄）；右抽屉走 translate 滑入滑出。
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
  // 抽屉得先留着才能播退场：它滑出去之后才是真的卸载
  const drawer = usePresence(drawerOpen, 240);
  // 1280 以上抽屉把内容让开：340 盖在 1180 的内容列上，会切掉右边一整列卡片。
  // 让位是瞬时位移，但跟着抽屉的挂载延迟一起收，否则抽屉还在往外滑、内容已经弹回去了。
  const pushRight = drawer.mounted && shell.width >= 1280;

  // [ ] 开合两侧；右抽屉打开时压一层 dialog 作用域，Esc 先关最上面那层
  useHotkeys("global", { "[": shell.toggleLeft, "]": shell.toggleRight });

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
        className="mx-auto flex w-full max-w-[1820px] items-start justify-center gap-5 px-5 transition-[padding-right] duration-[240ms] ease-out"
        style={pushRight ? { paddingRight: 364 } : undefined}
      >
        {/* 这一层是左栏的「面板」本身：宽度在这里过渡，展开/收起时才不会整块瞬移。
            两段内容共用一个容器，点收起时那一列从 288 挤到 64，内容列跟着变宽。 */}
        {shell.left !== "hidden" ? (
          <div
            data-shell-left={shell.left}
            style={{ width: shell.left === "full" ? LEFT_W_FULL : LEFT_W_RAIL }}
            // z-40：抬到底部渐隐层（AgentLauncher 那条 fixed inset-x-0 h-28，z-30）之上。
            // 那条渐变是为「卡片滚到底淡进纸面」做的，横跨整个视口，会顺手把左栏底部
            // 「稍后再看 / 快捷键 / 设置」刷成灰的，看着像被禁用了。两栏都是不透明纸色底，
            // 抬上去就把渐变挡回内容区，不用去算列宽。
            className="sticky top-[76px] z-40 h-[calc(100vh-96px)] min-w-0 shrink-0 overflow-hidden rounded-card border border-line bg-paper transition-[width] duration-[220ms] ease-out"
          >
            {shell.left === "full" ? (
              <AgentSidebar onCollapse={shell.toggleLeft} onHelp={onHelp} />
            ) : (
              <AgentSidebar collapsed onExpand={shell.toggleLeft} onHelp={onHelp} />
            )}
          </div>
        ) : null}

        <main id="main" tabIndex={-1} className="w-full min-w-0 max-w-[1180px] px-6 outline-none">
          {children}
        </main>

        {pinned && (shell.rightOpen || rail) ? (
          <RightRail
            className="rail-in sticky top-[76px] z-40 h-[calc(100vh-96px)] min-h-[420px] w-[320px] shrink-0"
            defaultTab={onItemPage ? "ai" : "saved"}
            onClose={dismissRail}
          />
        ) : null}
      </div>

      {drawer.mounted ? (
        // 不做遮罩：详情页右栏要能跟内容并排用，蒙一层会把点击吞掉
        <div
          data-shell-drawer="right"
          className={
            "drawer-in fixed inset-y-0 right-0 z-40 flex w-[340px] max-w-[92vw] flex-col p-3 transition duration-[240ms] ease-out " +
            (drawer.shown ? "translate-x-0 opacity-100" : "translate-x-full opacity-0")
          }
        >
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
