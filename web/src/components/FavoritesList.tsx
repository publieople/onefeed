import { Heart, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { listFavorites, removeFavorite, type FeedItem } from "../api";
import { useAgentActions } from "../agent/AgentProvider";
import { confirmDialog } from "./ui/Confirm";
import { platform } from "../platform";
import { timeAgo } from "../format";

/**
 * 右栏「收藏夹」：跟「稍后再看」是两套东西。
 *
 * 稍后再看是一键丢进去、按加入时间排、不带理由；收藏夹必写一句备注，
 * 列表里也是先看那句备注、再看标题 —— 它回答的是「我当时为什么留」。
 * 数据来自 /api/favorites，不跟信息流的 saved 筛选共用查询。
 */
export default function FavoritesList({ onOpen }: { onOpen?: () => void }) {
  const { openItem } = useAgentActions();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await listFavorites(50);
      setItems(data.items ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "取不到收藏夹");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onChanged = () => void load();
    window.addEventListener("onefeed:favorites", onChanged);
    return () => window.removeEventListener("onefeed:favorites", onChanged);
  }, [load]);

  const remove = async (item: FeedItem) => {
    const ok = await confirmDialog({
      title: "移出收藏夹？",
      body: "备注会一起删掉。稍后再看里的状态不受影响。",
      confirmText: "移出",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await removeFavorite(item.id);
      setItems((prev) => prev.filter((row) => row.id !== item.id));
    } catch {
      void load();
    }
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

  if (!items.length) {
    return (
      <div className="flex flex-1 items-center justify-center px-5 text-center text-[12.5px] leading-relaxed text-muted">
        收藏夹还是空的。
        <br />
        打开任意一条，点底部的「收藏」并写一句为什么留。
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 px-3.5 pb-2 pt-1 text-[11.5px] text-fade">
        <Heart size={11} />
        {items.length} 条
        <span className="ml-auto">按加入收藏夹倒序</span>
      </div>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain px-2 pb-2">
        {items.map((item) => {
          const meta = platform(item.platform);
          return (
            <li key={item.id} className="group rounded-lg p-1.5 transition hover:bg-wash/70">
              <div className="flex items-start gap-2">
                <button
                  onClick={() => {
                    openItem(item.id, item);
                    onOpen?.();
                  }}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="clamp-2 block text-[12.5px] leading-[1.5] text-ink">
                    {item.favorite_note || "（没写备注）"}
                  </span>
                  <span className="mt-1 flex items-center gap-1.5 text-[11px] text-fade">
                    <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: meta.tint }} />
                    {meta.label}
                    <span>·</span>
                    <span className="truncate">{item.title}</span>
                  </span>
                  <span className="mt-0.5 block text-[10.5px] text-fade">
                    {timeAgo(item.published_at)}
                  </span>
                </button>
                <button
                  onClick={() => void remove(item)}
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-fade opacity-0 transition hover:bg-wash hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                  aria-label={"把「" + item.title + "」移出收藏夹"}
                  title="移出收藏夹"
                >
                  <X size={12} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
