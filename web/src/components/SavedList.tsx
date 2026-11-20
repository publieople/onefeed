import { Loader2, RotateCcw, Star, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { agentSave, getJSON, type FeedItem, type FeedResponse } from "../api";
import { useAgentActions } from "../agent/AgentProvider";
import { timeAgo } from "../format";
import { platform } from "../platform";

/**
 * 稍后再看 = 信息流的 saved 筛选，不是第二份数据。
 * 卡片上的星标点一下会广播 onefeed:saved，这里跟着刷新，两边永远同一份。
 */
export default function SavedList({ onOpen }: { onOpen?: () => void }) {
  const { openItem } = useAgentActions();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [undo, setUndo] = useState<FeedItem | null>(null);
  // 正在淡出的那一行：先给 160ms 过渡，再真的从列表里摘掉
  const [leaving, setLeaving] = useState<string[]>([]);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getJSON<FeedResponse>("/api/feed?saved=1&sort=saved&limit=30");
      setItems(data.items ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "取不到稍后再看");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onSaved = () => void load();
    window.addEventListener("onefeed:saved", onSaved);
    return () => window.removeEventListener("onefeed:saved", onSaved);
  }, [load]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const remove = (item: FeedItem) => {
    // 列表瞬间少一行会让人怀疑「是不是点错了」，先让它缩着淡出去
    setLeaving((prev) => [...prev, item.id]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((row) => row.id !== item.id));
      setLeaving((prev) => prev.filter((id) => id !== item.id));
      setUndo(item);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setUndo(null), 5000);
    }, 160);
    void agentSave(item.id, false).catch(() => void load());
  };

  const restore = () => {
    const item = undo;
    if (!item) return;
    setUndo(null);
    void agentSave(item.id, true).then(() => void load()).catch(() => void load());
  };

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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {items.length ? (
        <div className="flex shrink-0 items-center gap-1.5 px-3.5 pb-2 pt-1 text-[11.5px] text-fade">
          <Star size={11} />
          {items.length} 条
          <span className="ml-auto">按加入时间倒序</span>
        </div>
      ) : (
        // 最后一条移出后仍然要能撤销：空态不能把撤销条一起吞掉
        <div className="flex flex-1 items-center justify-center px-5 text-center text-[12.5px] leading-relaxed text-muted">
          还没有稍后再看。
          <br />
          卡片上的星标就是这里 —— 看到想留的点一下。
        </div>
      )}
      {items.length ? (
      <ul data-smooth-scroll className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-2">
        {items.map((item) => {
          const meta = platform(item.platform);
          return (
            <li
              key={item.id}
              className={
                "group flex items-start gap-2.5 rounded-lg p-1.5 transition duration-[160ms] ease-out hover:bg-wash/70 " +
                (leaving.includes(item.id) ? "pointer-events-none -translate-x-1 opacity-0" : "")
              }
            >
              <button
                onClick={() => {
                  openItem(item.id, item);
                  onOpen?.();
                }}
                className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
              >
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
                    {timeAgo(item.saved_at || item.published_at)}
                  </span>
                </span>
              </button>
              <button
                onClick={() => remove(item)}
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-fade opacity-0 transition hover:bg-wash hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                aria-label={"把「" + item.title + "」移出稍后再看"}
                title="移出稍后再看"
              >
                <X size={12} />
              </button>
            </li>
          );
        })}
      </ul>
      ) : null}
      {undo ? (
        <div className="rise mx-2 mb-2 flex shrink-0 items-center gap-2 rounded-lg bg-solid px-3 py-2 text-[11.5px] text-solid-fg">
          <span className="truncate">已移出：{undo.title}</span>
          <button onClick={restore} className="ml-auto flex shrink-0 items-center gap-1 underline underline-offset-2">
            <RotateCcw size={11} />
            撤销
          </button>
        </div>
      ) : null}
    </div>
  );
}
