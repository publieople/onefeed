import { Loader2 } from "lucide-react";
import { useAgentActions, useAgentHistory } from "./AgentProvider";

/** 最近的对话：一眼看到聊过什么，点一下接着聊 */
export default function AgentHistory({ dense = false }: { dense?: boolean }) {
  const { items, loading, open } = useAgentHistory();
  const { resumeThread, newThread } = useAgentActions();
  if (!open) return null;
  return (
    <div className={"rise space-y-1.5 border-b border-line/60 " + (dense ? "pb-2" : "px-4 pb-3")}>
      <div className="flex items-center gap-2">
        <span className="text-[11.5px] text-fade">
          {loading ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" />
              正在翻…
            </span>
          ) : items.length ? (
            "接着上一段聊："
          ) : (
            "还没有别的对话。"
          )}
        </span>
        <button
          type="button"
          onClick={newThread}
          className="ml-auto text-[11px] text-fade underline-offset-2 transition hover:text-ink hover:underline"
        >
          开一段新的
        </button>
      </div>
      <div className={dense ? "max-h-[42vh] space-y-1 overflow-y-auto" : "space-y-1"}>
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => void resumeThread(item)}
            className="flex w-full items-center gap-2 rounded-lg border border-line/70 px-2.5 py-1.5 text-left transition hover:border-ink/20 hover:bg-wash/40"
          >
            <span className="min-w-0 flex-1 truncate text-[12.5px]">{item.title || "新对话"}</span>
            <span className="shrink-0 text-[11px] text-fade">{item.runs} 轮</span>
          </button>
        ))}
      </div>
    </div>
  );
}
