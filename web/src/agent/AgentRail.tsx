import { Sparkles, X } from "lucide-react";
import AgentComposer from "./AgentComposer";
import AgentHistory from "./AgentHistory";
import AgentThread from "./AgentThread";
import { useAgentActions, useAgentSession, useAgentSurface } from "./AgentProvider";

/**
 * 右栏里那块「跟 Agent 聊」的内容。外壳（宽度、圆角、滑动）由 RightRail 管，
 * 这里只负责对话本身 —— 所以右栏、抽屉、/agent 页都能装同一份。
 */
export function AgentRailBody() {
  const { focus } = useAgentSurface();
  const { ask } = useAgentActions();

  const presets = focus
    ? ["总结这一条", "跟同题的其他平台比比", "收藏这条并记一句为什么"]
    : ["今天有什么值得看的", "随便来点"];

  return (
    <>
      {focus ? (
        <div className="shrink-0 border-b border-line/60 px-3.5 py-2.5">
          <p className="truncate text-[12px] text-muted">正在看：{focus.title}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {presets.map((preset) => (
              <button
                key={preset}
                onClick={() => ask(preset)}
                className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-muted transition hover:border-ink/30 hover:text-ink"
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <AgentHistory dense />
      <AgentThread padding="px-3.5 py-3" />
      <div className="shrink-0 border-t border-line p-3">
        <AgentComposer />
      </div>
    </>
  );
}

/**
 * 独立的右栏外壳。App 外壳的右槽位（components/RightRail.tsx）会用 AgentRailBody 自己搭，
 * 这个默认导出留给需要单独立一栏的场景。
 */
export default function AgentRail() {
  const { close } = useAgentActions();
  const { turns } = useAgentSession();
  return (
    <aside
      data-agent-surface="rail"
      data-vt="agent"
      style={{ viewTransitionName: "of-agent" }}
      aria-label="AI 助手"
      className="sticky top-[76px] flex h-[calc(100vh-96px)] min-h-[420px] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_10px_30px_rgba(26,22,14,0.06)]"
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3.5">
        <Sparkles size={14} className="text-muted" />
        <span className="text-[13px] font-medium">找内容</span>
        <span className="text-[11.5px] text-fade">
          {turns.length ? "这是刚才那轮" : "随时接着聊"}
        </span>
        <button
          onClick={close}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink"
          aria-label="收起右栏"
          title="收起（Esc）"
        >
          <X size={14} />
        </button>
      </div>
      <AgentRailBody />
    </aside>
  );
}
