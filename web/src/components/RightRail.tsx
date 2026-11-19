import { Bookmark, History, Layers, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAgentActions, useAgentSurface } from "../agent/AgentProvider";
import { AgentRailBody } from "../agent/AgentRail";
import { useRailSlot } from "../layout/RailSlot";
import { platform } from "../platform";
import SavedList from "./SavedList";

export type RailTab = "saved" | "ai" | "siblings";

const ICON = { saved: Bookmark, ai: Sparkles, siblings: Layers } as const;
const LABEL: Record<RailTab, string> = { saved: "稍后再看", ai: "AI 助手", siblings: "同题" };

/**
 * 右栏槽位：一个 320 宽的栏，里面按场景换三块内容。
 * 详情页默认 AI（跟内容并排聊），信息流默认稍后再看；
 * 只在 ≥1800 常驻，往下是抽屉（由 Shell 挂，抽屉里也是这同一个组件）。
 */
export default function RightRail({
  className = "",
  defaultTab = "saved",
  onClose,
}: {
  className?: string;
  defaultTab?: RailTab;
  onClose?: () => void;
}) {
  const { open: agentOpen, mode } = useAgentSurface();
  const { close, toggleHistory } = useAgentActions();
  const { siblings } = useRailSlot();
  const [tab, setTab] = useState<RailTab>(defaultTab);

  const tabs: RailTab[] = siblings.length ? ["saved", "ai", "siblings"] : ["saved", "ai"];
  const key = tabs.join(",");

  // Agent 以「右栏」形态打开（详情页 ≥1080）时，这一栏自动让给对话。
  // 信息流上打开的是底部抽屉，右栏不该跟着切成对话 —— 同一段话会在屏幕上出现两次。
  useEffect(() => {
    if (agentOpen && mode === "rail") setTab("ai");
  }, [agentOpen, mode]);

  // 对话收起后右栏还留着，把内容还给稍后再看，别停在一条已经结束的对话上。
  // 只认「从开到关」这一跳：挂载时 agentOpen 就是 false，那时不能把详情页默认的 AI 页顶掉。
  const prevOpen = useRef(agentOpen);
  useEffect(() => {
    if (prevOpen.current && !agentOpen) setTab((prev) => (prev === "ai" ? "saved" : prev));
    prevOpen.current = agentOpen;
  }, [agentOpen]);

  // 左栏 / 信息流工具栏的「稍后再看」：外壳负责把抽屉拉开，这里只负责切到那一页
  useEffect(() => {
    const onRail = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: RailTab }>).detail;
      setTab(detail?.tab ?? "saved");
    };
    window.addEventListener("onefeed:rail", onRail);
    return () => window.removeEventListener("onefeed:rail", onRail);
  }, []);

  // 同题条目在切走详情页后会清空，那时不能停在「同题」上
  useEffect(() => {
    if (!tabs.includes(tab)) setTab("saved");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tab]);

  const presenting = tab === "ai" && agentOpen && mode === "rail";

  return (
    <aside
      data-rail="slot"
      data-agent-surface={presenting ? "rail" : undefined}
      data-vt={presenting ? "agent" : undefined}
      style={presenting ? { viewTransitionName: "of-agent" } : undefined}
      aria-label={presenting ? "AI 助手" : "右侧栏"}
      className={
        "flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_10px_30px_rgba(20,20,20,0.06)] " +
        className
      }
    >
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-line px-2">
        <span role="tablist" aria-label="右栏内容" className="flex items-center gap-0.5">
          {tabs.map((id) => {
            const Icon = ICON[id];
            const on = id === tab;
            return (
              <button
                key={id}
                role="tab"
                aria-selected={on}
                onClick={() => setTab(id)}
                className={
                  "flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] transition " +
                  (on ? "bg-wash text-ink" : "text-muted hover:text-ink")
                }
              >
                <Icon size={12.5} />
                {LABEL[id]}
              </button>
            );
          })}
        </span>
        {tab === "ai" ? (
          <button
            onClick={() => void toggleHistory()}
            className="ml-auto flex h-7 w-7 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink"
            aria-label="最近的对话"
            title="最近的对话"
          >
            <History size={13} />
          </button>
        ) : null}
        <button
          onClick={() => (presenting ? close() : onClose?.())}
          className={
            "flex h-7 w-7 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink " +
            (tab === "ai" ? "" : "ml-auto")
          }
          aria-label="收起右栏"
          title="收起右栏"
        >
          <X size={14} />
        </button>
      </div>

      {tab === "ai" ? (
        <AgentRailBody />
      ) : tab === "saved" ? (
        <SavedList onOpen={onClose} />
      ) : (
        <SiblingList />
      )}
    </aside>
  );
}

/** 同题：同一件事还有哪些平台在讲，点一下换到那条 */
function SiblingList() {
  const { siblings } = useRailSlot();
  const { openItem } = useAgentActions();
  if (!siblings.length) {
    return <p className="px-3.5 py-10 text-center text-[12.5px] text-muted">这条没有别的平台在讲。</p>;
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="shrink-0 px-3.5 pb-2 pt-1 text-[11.5px] text-fade">
        同一件事还在 {siblings.length} 个平台出现
      </p>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-2 pb-2">
        {siblings.map((sib) => {
          const meta = platform(sib.platform);
          return (
            <li key={sib.id}>
              <button
                onClick={() => openItem(sib.id)}
                className="w-full rounded-lg p-1.5 text-left transition hover:bg-wash/70"
              >
                <span className="clamp-2 block text-[12.5px] leading-[1.45]">{sib.title}</span>
                <span className="mt-1 flex items-center gap-1.5 text-[11px] text-fade">
                  <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: meta.tint }} />
                  {meta.label}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
