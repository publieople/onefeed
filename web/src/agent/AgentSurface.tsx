import { History, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import FilterBox from "../components/FilterBox";
import { useLauncherReveal } from "../motion/useLauncherReveal";
import { usePresence } from "../motion/usePresence";
import { useAgentActions, useAgentHistory, useAgentSession, useAgentSurface } from "./AgentProvider";
import AgentComposer from "./AgentComposer";
import AgentHistory from "./AgentHistory";
import AgentThread from "./AgentThread";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

const LAUNCH_HINTS = [
  "今天 B 站有什么值得看的 AI 内容",
  "随便来点，别老是同一个平台",
  "把这周热度最高的几条挑出来",
];

/** 唤起器：没打开时只剩这一条。信息流上是底部胶囊，其他页是右下角圆钮。 */
export function AgentLauncher() {
  const { onItemPage, pinned, hintIndex, turns } = { ...useAgentSurface(), ...useAgentSession() };
  const { openWith } = useAgentActions();
  // 滚动感应：往下翻时它收起来让出内容，往回滚一点、或指针贴到底边再出来。
  // 收起用的是位移 + 透明（节点还在），所以还要把 tabIndex 和 pointer-events 一起关掉。
  const { shown, hold } = useLauncherReveal();
  const lift = shown ? "translate-y-0 opacity-100" : "translate-y-[130%] opacity-0";
  const reach = shown ? "pointer-events-auto" : "pointer-events-none";
  // ≥1800 右栏常驻，详情页再挂个圆钮就是两个入口打架
  if (onItemPage && pinned) return null;
  // 入口贴内容栏的右沿，不贴屏幕右沿：页面主体有 1240 上限，贴屏幕会在宽屏上飘到空白里去，
  // 视觉上跟内容脱节。代位盒子（motion/ghost.ts）算的是同一组边距，两边必须一起改。
  if (onItemPage) {
    return (
      <div
        data-agent-launcher-wrap="corner"
        // 夹在内容列里（外壳把两栏宽度写成 CSS 变量）：只铺视口会在宽屏上飘到空白里
        style={{ left: "var(--shell-left-w, 0px)", right: "var(--shell-right-w, 0px)" }}
        className={
          "pointer-events-none fixed bottom-0 z-30 px-6 pb-5 transition duration-300 ease-out " + lift
        }
      >
        <div className="mx-auto flex w-full max-w-[1400px] justify-end">
          <button
            onClick={() => openWith()}
            onPointerEnter={() => hold(true)}
            onPointerLeave={() => hold(false)}
            onFocus={() => hold(true)}
            onBlur={() => hold(false)}
            data-agent-launcher="corner"
            tabIndex={shown ? 0 : -1}
            className={
              "flex h-10 items-center gap-2 rounded-full border border-line/70 bg-paper/85 pl-2.5 pr-4 text-[12.5px] text-muted shadow-[0_4px_14px_rgba(20,20,20,0.08)] transition duration-200 hover:-translate-y-0.5 hover:border-ink/25 hover:bg-paper hover:text-ink " +
              reach
            }
            aria-label="打开 AI 助手"
            title="问 OneFeed（/ 或 ⌘K）"
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-solid text-solid-fg">
              <Sparkles size={12} />
            </span>
            AI 助手
            {turns.length ? <span className="h-1.5 w-1.5 rounded-full bg-ink" aria-hidden /> : null}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div
      data-agent-launcher-wrap="pill"
      style={{ left: "var(--shell-left-w, 0px)", right: "var(--shell-right-w, 0px)" }}
      className={
        "pointer-events-none fixed bottom-0 z-30 px-6 pb-4 transition duration-300 ease-out " + lift
      }
    >
      {/* 底部渐隐：卡片滚到这里会淡进纸面，而不是被胶囊硬切一条直线。
          用渐变而不是模糊（backdrop-filter 在长列表上要重绘整屏，PF-1 刚去掉）。
          渐隐层跟着唤起器一起位移/淡出，收起时底部不留一条没有内容的白雾。 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-paper via-paper/85 to-transparent"
      />
      <div className="relative mx-auto flex w-full max-w-[1400px] justify-center">
        {/* 平时半透明、薄一点；悬停/聚焦才浮起来。整条不抢内容，但一直够得着。 */}
        <button
          onClick={() => openWith()}
          onPointerEnter={() => hold(true)}
          onPointerLeave={() => hold(false)}
          onFocus={() => hold(true)}
          onBlur={() => hold(false)}
          data-agent-launcher="pill"
          tabIndex={shown ? 0 : -1}
          className={
            "flex h-11 w-full max-w-[760px] items-center gap-2 rounded-full border border-line/70 bg-paper/80 px-3 text-left shadow-[0_4px_14px_rgba(20,20,20,0.06)] transition duration-200 hover:-translate-y-0.5 hover:border-ink/25 hover:bg-paper hover:shadow-[0_10px_26px_rgba(20,20,20,0.12)] focus-visible:-translate-y-0.5 focus-visible:border-ink/25 focus-visible:bg-paper " +
            reach
          }
          aria-label="打开 AI 助手"
        >
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg">
            <Sparkles size={12} />
          </span>
          <span className="flex-1 truncate text-[12.5px] text-fade">
            问 OneFeed：{LAUNCH_HINTS[hintIndex % LAUNCH_HINTS.length]}
          </span>
          <kbd className="hidden shrink-0 rounded border border-line px-1.5 py-0.5 text-[10px] text-fade md:block">/</kbd>
        </button>
      </div>
    </div>
  );
}

/**
 * 底部抽屉：窄屏、非详情页，以及详情页但不够宽的时候。
 *
 * shown / named 由外层给：关闭时 mode 立刻变成 closed，但面板得先滑下去再卸载，
 * 所以挂载与展示分成两件事（motion/usePresence）。
 * named=false 用于「抽屉正在退场、右栏已经接管」的那一帧 —— 同一时刻只能有一个
 * of-agent，两个同名会让浏览器直接取消整段转场。
 */
export function AgentSheet({ shown = true, named = true }: { shown?: boolean; named?: boolean }) {
  const { open } = useAgentSurface();
  const { open: historyOpen } = useAgentHistory();
  const { close, toggleHistory } = useAgentActions();
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const [manual, setManual] = useState(false);

  // Tab 在抽屉里循环
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const root = sheetRef.current;
      if (!root) return;
      const nodes = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null,
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && (active === first || !root.contains(active))) {
        e.preventDefault();
        last.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // 挂到 body：切页动画会给页面容器加 transform，fixed 元素留在里面会跟着跑。
  // data-vt="agent" + 常驻名字：抽屉和详情页右栏是同一个东西换了位置，
  // 浏览器靠这个把两端插成一段「从底部滑到右侧」的位移。
  return createPortal(
    <div
      data-agent-surface="sheet"
      role="dialog"
      aria-modal="true"
      aria-label="找内容"
      ref={sheetRef}
      style={{ left: "var(--shell-left-w, 0px)", right: "var(--shell-right-w, 0px)" }}
      className={
        "sheet-in fixed bottom-0 z-40 flex justify-center px-6 pb-4 transition duration-[220ms] ease-out " +
        (shown ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0")
      }
    >
      <div className="flex w-full max-w-[760px] flex-col gap-3">
        {/* 名字挂在面板本身，不挂外层那条通栏容器：外层是 1270 宽，
            插值出来的盒子会横着铺满整屏，看不出「从唤起器长出来」。 */}
        <div
          data-vt="agent"
          style={named ? { viewTransitionName: "of-agent" } : undefined}
          className="flex max-h-[62vh] min-h-[200px] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_18px_50px_rgba(20,20,20,0.14)]"
        >
          <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
            <Sparkles size={14} className="text-ink" />
            <span className="text-[13px] font-medium">找内容</span>
            <button
              onClick={() => void toggleHistory()}
              className="ml-auto rounded p-1 text-fade transition hover:bg-wash hover:text-ink"
              aria-label="最近的对话"
              title="最近的对话"
            >
              <History size={15} />
            </button>
            <button
              onClick={close}
              className="rounded p-1 text-fade transition hover:bg-wash hover:text-ink"
              aria-label="收起"
              title="收起（Esc）"
            >
              <X size={15} />
            </button>
          </div>
          {/* 这层滚动容器必须跟着历史开关一起装卸：历史收起时它是个空的 flex-1，
              会把整块高度占满，把下面的话往底下一挤 —— 顶上空一大片，内容还被裁掉 */}
          {historyOpen ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <AgentHistory />
            </div>
          ) : null}
          <AgentThread />
          <div className="border-t border-line px-4 py-2.5">
            <button
              onClick={() => setManual((v) => !v)}
              className="text-[12px] text-fade transition hover:text-ink"
            >
              {manual ? "收起手动筛选" : "手动筛选"}
            </button>
            {manual ? (
              <FilterBox
                value=""
                parsed={null}
                onSubmit={(q) => {
                  window.dispatchEvent(new CustomEvent("onefeed:filter", { detail: { keyword: q } }));
                  close();
                }}
              />
            ) : null}
          </div>
        </div>
        <AgentComposer wide />
      </div>
    </div>,
    document.body,
  );
}

export default function AgentSurface() {
  const { mode, onAgentPage } = useAgentSurface();
  // 抽屉的挂载寿命要比 mode==="sheet" 长一截：关闭时先滑下去，滑完再卸载。
  // 唤起器同期先不渲染，否则它会在抽屉退场的 220ms 里从底下冒出来抢镜。
  const sheet = usePresence(mode === "sheet", 220);
  if (onAgentPage) return null;
  return (
    <>
      {mode === "closed" || !sheet.mounted ? <AgentLauncher /> : null}
      {sheet.mounted ? <AgentSheet shown={sheet.shown} named={mode === "sheet"} /> : null}
    </>
  );
}