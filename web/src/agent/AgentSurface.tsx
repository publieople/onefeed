import { History, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import FilterBox from "../components/FilterBox";
import { useAgentActions, useAgentSession, useAgentSurface } from "./AgentProvider";
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
  const { onItemPage, hintIndex, turns } = { ...useAgentSurface(), ...useAgentSession() };
  const { openWith } = useAgentActions();
  if (onItemPage) {
    return (
      <button
        onClick={() => openWith()}
        className="fixed bottom-5 right-5 z-30 flex h-11 items-center gap-2 rounded-full border border-line bg-paper/95 pl-3 pr-4 text-[12.5px] text-muted shadow-[0_10px_30px_rgba(20,20,20,0.14)] transition hover:border-ink/30 hover:text-ink"
        aria-label="打开 AI 助手"
        title="问 OneFeed（/ 或 ⌘K）"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-solid text-solid-fg">
          <Sparkles size={12} />
        </span>
        AI 助手
        {turns.length ? <span className="h-1.5 w-1.5 rounded-full bg-ink" aria-hidden /> : null}
      </button>
    );
  }
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-4">
      <button
        onClick={() => openWith()}
        className="pointer-events-auto flex h-12 w-full max-w-[760px] items-center gap-2 rounded-full border border-line bg-paper/95 px-3 text-left shadow-[0_10px_30px_rgba(20,20,20,0.12)] transition hover:border-ink/30"
        aria-label="打开 AI 助手"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg">
          <Sparkles size={13} />
        </span>
        <span className="flex-1 truncate text-[13px] text-fade">
          问 OneFeed：{LAUNCH_HINTS[hintIndex % LAUNCH_HINTS.length]}
        </span>
        <kbd className="hidden shrink-0 rounded border border-line px-1.5 py-0.5 text-[10px] text-fade md:block">/</kbd>
      </button>
    </div>
  );
}

/** 底部抽屉：窄屏、非详情页，以及详情页但不够宽的时候 */
export function AgentSheet() {
  const { open } = useAgentSurface();
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

  if (!open) return null;

  // 挂到 body：切页动画会给页面容器加 transform，fixed 元素留在里面会跟着跑
  return createPortal(
    <div
      data-agent-surface="sheet"
      role="dialog"
      aria-modal="true"
      aria-label="找内容"
      ref={sheetRef}
      className="fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-4"
    >
      <div className="flex w-full max-w-[760px] flex-col gap-3">
        <div className="flex max-h-[62vh] min-h-[320px] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_18px_50px_rgba(20,20,20,0.14)]">
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
          <div className="min-h-0 flex-1 overflow-y-auto">
            <AgentHistory />
          </div>
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
  if (onAgentPage) return null;
  return mode === "closed" ? <AgentLauncher /> : mode === "sheet" ? <AgentSheet /> : null;
}
