import { Loader2, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { agentSummaries, type SummarizedItem } from "../api";
import { useAgentActions } from "../agent/AgentProvider";
import { platform } from "../platform";
import { timeAgo } from "../format";

/**
 * 右栏「AI 总结」：最近生成过总结的条目。
 *
 * 数据是总结缓存的 join 结果，不是第二份列表 —— 在详情页点「重新总结」或者
 * 第一次生成完，广播 onefeed:summary，这里跟着刷新。
 */
export default function SummaryList({ onOpen }: { onOpen?: () => void }) {
  const { openItem } = useAgentActions();
  const [items, setItems] = useState<SummarizedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await agentSummaries(30);
      setItems(data.items ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "取不到 AI 总结");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onSummary = () => void load();
    window.addEventListener("onefeed:summary", onSummary);
    return () => window.removeEventListener("onefeed:summary", onSummary);
  }, [load]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 py-10 text-[12.5px] text-fade">
        <Loader2 size={13} className="animate-spin" />
        正在翻…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3.5 text-[12.5px] text-muted">
        {error}
        <button onClick={() => void load()} className="ml-2 underline underline-offset-2">
          再试一次
        </button>
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="flex flex-1 items-center justify-center px-5 text-center text-[12.5px] leading-relaxed text-muted">
        还没有总结过。
        <br />
        点开任意一条，Agent 会把它读成几条要点；读过的都收在这里。
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 px-3.5 pb-2 pt-1 text-[11.5px] text-fade">
        <Sparkles size={11} />
        {items.length} 条
        <span className="ml-auto">按总结时间倒序</span>
      </div>
      <ul data-smooth-scroll className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-2 pb-2">
        {items.map((item) => {
          const meta = platform(item.platform);
          return (
            <li key={item.id}>
              <button
                data-summary-row={item.id}
                onClick={() => {
                  openItem(item.id, item);
                  onOpen?.();
                }}
                className="w-full rounded-lg p-1.5 text-left transition hover:bg-wash/70"
              >
                <span className="flex items-start gap-2.5">
                  {item.cover ? (
                    <img
                      src={item.cover}
                      alt=""
                      loading="lazy"
                      className="h-11 w-11 shrink-0 rounded-md object-cover"
                    />
                  ) : (
                    <span
                      aria-hidden
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-wash text-[10px] text-fade"
                    >
                      {meta.label}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="clamp-2 block text-[12.5px] leading-[1.45]">{item.title}</span>
                    <span className="mt-1 flex items-center gap-1.5 text-[11px] text-fade">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: meta.tint }} />
                      {meta.label}
                      <span>·</span>
                      {timeAgo(item.summary_at || item.published_at)}
                    </span>
                  </span>
                </span>
                {item.summary_tldr ? (
                  <span className="clamp-2 mt-1 block pl-[3.25rem] text-[11.5px] leading-[1.55] text-muted">
                    {item.summary_tldr}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
