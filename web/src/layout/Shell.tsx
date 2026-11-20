import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import AgentSidebar from "../agent/AgentSidebar";
import { useAgentActions, useAgentSurface } from "../agent/AgentProvider";
import type { Health, RunState } from "../api";
import RightRail, { type RailTab } from "../components/RightRail";
import TopBar from "../components/TopBar";
import { DUR, EASE } from "../motion/tokens";
import { popScope, pushScope, useHotkeys } from "../motion/useHotkeys";
import { usePresence } from "../motion/usePresence";
import { useShell } from "./useShell";

/** 左栏两档宽度：展开 240、图标轨 64。写常量是因为宽度要拿去过渡，不能再靠 class 切换。 */
const LEFT_W_FULL = 240;
const LEFT_W_RAIL = 64;
/** 右栏钉住时的宽度。和 ghost.ts 里的代位盒子口径一致。 */
const RIGHT_W = 320;

/**
 * 外壳：左 Agent 工作台 / 中内容 / 右槽位，三栏贴边。
 *
 * 形态照搬常规社交平台（B 站 / 小红书 / 抖音）：顶栏通栏，两栏各贴一侧边缘、
 * 上下贯通到底，中间那列吃掉剩下的全部宽度 —— 而不是三张浮在纸上的圆角卡片。
 * 贴边让内容有「一直滚不到头」的连续感，也让窄屏时两栏可以整块收掉不留缝。
 *
 * 断点（见 useShell）：1440 起右栏可钉住（默认仍是关的，] 打开），
 * 1200 起左栏可展开 240，960 起退成 64 图标轨，再窄两栏都不渲染。
 *
 * 左栏展开 = 这一列从 64 变宽成 240，中间列被 flex 挤窄；不是浮层。
 * 宽度不做过渡（实测逐帧重排 30 张卡，收栏只有 26.8fps，见 theme.css 的注释），
 * 换宽一步到位，由中间列的 200ms 位移+淡入接住这一下；右抽屉仍走 translate 滑入滑出。
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
  /**
   * 左栏点「收藏夹」时这一栏是关着的，事件比挂载先到——
   * 光靠栏内的监听接不住，所以外壳记住要开哪一页，挂载时直接落在那一页。
   */
  const [railTab, setRailTab] = useState<RailTab | null>(null);
  const drawerOpen = !pinned && (shell.rightOpen || rail);
  // 抽屉得先留着才能播退场：它滑出去之后才是真的卸载
  const drawer = usePresence(drawerOpen, 240);

  /**
   * 左栏换宽之后，给中间列挂 200ms 的位移+淡入。
   * 栏宽是硬切的（过渡会逐帧重排卡片），这一下靠合成层的动效接住，
   * 读起来像「内容有方向地归位」，而不是整块跳过去。
   */
  const [settle, setSettle] = useState<"" | "expand" | "collapse">("");
  const prevLeft = useRef(shell.left);
  useEffect(() => {
    const prev = prevLeft.current;
    prevLeft.current = shell.left;
    if (prev === shell.left) return;
    const dir =
      prev === "full" && shell.left === "rail"
        ? "collapse"
        : prev === "rail" && shell.left === "full"
          ? "expand"
          : "";
    if (!dir) return;
    setSettle(dir);
    const timer = window.setTimeout(() => setSettle(""), 220);
    return () => window.clearTimeout(timer);
  }, [shell.left]);

  const leftW = shell.left === "hidden" ? 0 : shell.left === "full" ? LEFT_W_FULL : LEFT_W_RAIL;
  const railOpen = pinned && (shell.rightOpen || rail);
  const reduce = useReducedMotion() ?? false;

  /**
   * 两栏的真实宽度写成 CSS 变量给视口级浮层用。
   *
   * 底部唤起器是 fixed 的，如果还按 inset-x-0 铺满视口，它会在两栏底部的空白里
   * 居中，跟内容列对不上（宽屏上偏左、右栏打开时偏右）。浮层拿这两个变量把自己
   * 夹在内容列上，代位盒子（motion/ghost.ts）再实测 #main，两边口径一致。
   */
  useEffect(() => {
    document.documentElement.style.setProperty("--shell-left-w", leftW + "px");
  }, [leftW]);
  // 右栏那一半：只在开合的那一刻写一次。
  // 曾经逐帧写（让浮层跟着栏的宽度动画一起挪），实测每帧 65–102ms ——
  // 根元素上的自定义属性被整棵树继承，写一次就是一次全站样式重算。
  // 现在浮层自己带 shell-inset-x 的 left/right 过渡，由 CSS 补间，别再回来逐帧写。
  useEffect(() => {
    document.documentElement.style.setProperty("--shell-right-w", (railOpen ? RIGHT_W : 0) + "px");
  }, [railOpen]);
  // 离开外壳（比如独立的会话页）时清掉，别把别人也夹住
  useEffect(() => {
    const root = document.documentElement;
    return () => {
      root.style.removeProperty("--shell-left-w");
      root.style.removeProperty("--shell-right-w");
    };
  }, []);

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

  /**
   * 左栏和工具栏上的「稍后再看 / 收藏夹 / AI 总结」只发一条 onefeed:rail 事件，
   * 真正把这一栏拉开的是外壳：栏本身默认是关的，不在这里接住，点了就像没反应。
   */
  const openRight = shell.setRightOpen;
  useEffect(() => {
    const onRail = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: RailTab }>).detail;
      setRailTab(detail?.tab ?? "saved");
      // Agent 正占着这一栏时，先把它收掉，否则列表会被对话顶掉
      if (rail) close();
      openRight(true);
    };
    window.addEventListener("onefeed:rail", onRail);
    return () => window.removeEventListener("onefeed:rail", onRail);
  }, [rail, close, openRight]);

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

      <div className="flex w-full items-start">
        {/* 这一层是左栏本身：宽度在这里过渡，展开/收起时才不会整块瞬移。
            两段内容共用一个容器，点收起时那一列从 240 挤到 64，中间列跟着变宽。 */}
        {shell.left !== "hidden" ? (
          <div
            data-shell-left={shell.left}
            style={{ width: leftW }}
            // z-40：抬到底部渐隐层（AgentLauncher 那条 fixed inset-x-0 h-28，z-30）之上。
            // 那条渐变是为「卡片滚到底淡进纸面」做的，横跨整个视口，会顺手把左栏底部
            // 「稍后再看 / 快捷键 / 设置」刷成灰的，看着像被禁用了。两栏都是不透明纸色底，
            // 抬上去就把渐变挡回内容区，不用去算列宽。
            // top-[57px] / 100vh-57px：顶栏 h-14 加 1px 分隔线才是它真正的下沿，
            // 用 top-14 会让栏底多出 1px 落到视口外
            className="shell-col sticky top-[57px] z-40 h-[calc(100vh-57px)] min-w-0 shrink-0 overflow-hidden border-r border-line bg-paper"
          >
            {shell.left === "full" ? (
              <AgentSidebar onCollapse={shell.toggleLeft} onHelp={onHelp} />
            ) : (
              <AgentSidebar collapsed onExpand={shell.toggleLeft} onHelp={onHelp} />
            )}
          </div>
        ) : null}

        {/* 中间列吃掉剩下的宽度：不再写死 max-w，宽屏就真的铺满。
            可读性靠内层的 1240 上限，而不是把整列缩成一个居中的窄条。 */}
        <main
          id="main"
          tabIndex={-1}
          className={
            "min-w-0 flex-1 px-6 outline-none" +
            (settle === "expand" ? " content-settle-expand" : settle === "collapse" ? " content-settle-collapse" : "")
          }
        >
          {/* data-content：内容列的真正边界（含 1400 上限），代位盒子按它算落点，
              而不是量整条 main —— 宽屏上 main 比内容宽，盒子会飘到右侧空白里 */}
          <div data-content className="mx-auto w-full max-w-[1400px]">
            {children}
          </div>
        </main>

        {/* 右栏：宽度补间，不是 fade-in。栏宽 0 起、AnimatePresence 留到退场结束，
            内层固定 320 且右对齐 —— 宽度从右缘向左长，里面标题不会跟着横向滑动。 */}
        <AnimatePresence initial={false}>
          {railOpen ? (
            <motion.div
              key="rail"
              className="sticky top-[57px] z-40 flex h-[calc(100vh-57px)] min-h-[420px] shrink-0 justify-end overflow-hidden border-l border-line"
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: RIGHT_W, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={reduce ? { duration: 0 } : { duration: DUR.page, ease: EASE }}
            >
              <RightRail
                className="h-full w-[320px] shrink-0"
                defaultTab={railTab ?? (onItemPage ? "ai" : "saved")}
                onClose={dismissRail}
              />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      {drawer.mounted ? (
        // 不做遮罩：详情页右栏要能跟内容并排用，蒙一层会把点击吞掉。
        // 窄屏也没有「内容让位」——340 的抽屉在这个宽度上本来就盖在边上，
        // 强行挤内容会把卡片压成一条缝，滑过去再收起还要再抖一次。
        <div
          data-shell-drawer="right"
          className={
            // top-[57px]：从顶栏下沿开始，别把顶栏右侧的刷新/主题/设置盖掉
            "drawer-in fixed bottom-0 right-0 top-[57px] z-40 flex w-[340px] max-w-[92vw] flex-col p-3 transition duration-[240ms] ease-out " +
            (drawer.shown ? "translate-x-0 opacity-100" : "translate-x-full opacity-0")
          }
        >
          <RightRail
            className="h-full rounded-card border border-line shadow-[0_18px_50px_rgba(20,20,20,0.14)]"
            defaultTab={railTab ?? (onItemPage ? "ai" : "saved")}
            onClose={dismissRail}
          />
        </div>
      ) : null}
    </div>
  );
}