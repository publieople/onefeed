import { History, Sparkles, X } from "lucide-react";
import { useAgentActions, useAgentSession, useAgentSurface } from "./AgentProvider";
import AgentComposer from "./AgentComposer";
import AgentHistory from "./AgentHistory";
import AgentThread from "./AgentThread";

/**
 * 详情页右栏：Agent 和数据并排站着。
 * 这一形态是为了修「Agent 打开一条内容后自己消失」——换页面、看原文时它都在。
 */
export default function AgentRail() {
  const { focus } = useAgentSurface();
  const { turns } = useAgentSession();
  const { close, toggleHistory, ask, inputRef } = useAgentActions();

  const presets = focus
    ? ["总结这一条", "跟同题的其他平台比比", "收藏这条并记一句为什么"]
    : ["今天有什么值得看的", "随便来点"];

  return (
    <aside
      data-agent-surface="rail"
      aria-label="AI 助手"
      className="sticky top-[76px] flex h-[calc(100vh-96px)] min-h-[420px] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_10px_30px_rgba(20,20,20,0.06)]"
    >
      <div className="flex items-center gap-2 border-b border-line px-3.5 py-2.5">
        <Sparkles size={14} className="text-ink" />
        <span className="text-[13px] font-medium">找内容</span>
        <span className="text-[11px] text-fade">{turns.length ? `${turns.length} 条消息` : "随时接着聊"}</span>
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
          aria-label="收起右栏"
          title="收起（Esc）"
        >
          <X size={15} />
        </button>
      </div>

      {focus ? (
        <div className="border-b border-line/70 px-3.5 py-2.5">
          <p className="truncate text-[11.5px] text-fade" title={focus.title}>
            正在看：<span className="text-muted">{focus.title}</span>
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {presets.map((preset) => (
              <button
                key={preset}
                onClick={() => {
                  inputRef.current?.focus();
                  void ask(preset);
                }}
                className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-muted transition hover:border-ink/25 hover:text-ink"
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <AgentHistory dense />
      <AgentThread padding="px-3.5 py-3" />

      <div className="border-t border-line p-3">
        <AgentComposer />
      </div>
    </aside>
  );
}
