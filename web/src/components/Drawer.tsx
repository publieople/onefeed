import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Heart, X } from "lucide-react";
import { useEffect, useState } from "react";
import { getJSON, type FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { num, timeAgo } from "../format";

interface Detail {
  item: FeedItem;
  siblings: { id: string; platform: string; title: string; author: string; url: string; published_at: number }[];
}

export default function Drawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    setData(null);
    setError("");
    const controller = new AbortController();
    getJSON<Detail>("/api/item/" + encodeURIComponent(id), controller.signal)
      .then(setData)
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const item = data?.item;
  const stats = item
    ? [
        { label: "播放", value: item.view_count },
        { label: "点赞", value: item.like_count },
        { label: "评论", value: item.comment_count },
        { label: "分享", value: item.share_count },
      ].filter((s) => s.value > 0)
    : [];

  return (
    <AnimatePresence>
      {id ? (
        <motion.div
          className="fixed inset-0 z-40"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/25" onClick={onClose} />
          <motion.aside
            className="absolute right-0 top-0 flex h-full w-full max-w-[480px] flex-col overflow-y-auto bg-white shadow-pop"
            initial={{ x: 40 }}
            animate={{ x: 0 }}
            exit={{ x: 40 }}
            transition={{ type: "tween", duration: 0.22 }}
          >
            {!item ? (
              <div className="flex h-full items-center justify-center text-[13px] text-fade">
                {error ? "加载失败：" + error : "加载中…"}
              </div>
            ) : (
              <div className="p-7">
                <div className="flex items-center gap-2 text-[12px] text-muted">
                  <span className="h-[7px] w-[7px] rounded-full" style={{ background: platform(item.platform).tint }} />
                  {platform(item.platform).label}
                  <span className="rounded border border-line px-1.5 py-0.5 text-[11px] text-fade">
                    {KIND_LABEL[item.kind] ?? item.kind}
                  </span>
                  <button onClick={onClose} className="ml-auto rounded-full p-1 text-fade hover:bg-wash hover:text-ink">
                    <X size={17} />
                  </button>
                </div>

                <h2 className="mt-3 text-[21px] font-semibold leading-[1.4] tracking-tight">{item.title}</h2>
                <div className="mt-2 flex items-center gap-2 text-[12px] text-muted">
                  {item.author ? <span>{item.author}</span> : null}
                  {item.author && item.published_at ? <span className="text-fade">·</span> : null}
                  <span className="text-fade">{timeAgo(item.published_at)}</span>
                </div>

                {item.cover ? (
                  <img
                    src={item.cover}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="mt-4 w-full rounded-lg object-cover"
                  />
                ) : null}

                {item.images.map((src) => (
                  <img
                    key={src}
                    src={src}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="mt-2 w-full rounded-lg object-cover"
                  />
                ))}

                {stats.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {stats.map((s) => (
                      <div key={s.label} className="min-w-[86px] rounded-lg border border-line px-3 py-2">
                        <div className="text-[15px] font-semibold tabular-nums">{num(s.value)}</div>
                        <div className="text-[11px] text-fade">{s.label}</div>
                      </div>
                    ))}
                  </div>
                ) : null}

                {item.text ? (
                  <p className="mt-4 whitespace-pre-wrap text-[13px] leading-[1.85] text-muted">{item.text}</p>
                ) : null}

                {item.tags?.length ? (
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {item.tags.slice(0, 8).map((t) => (
                      <span key={t} className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">
                        #{t}
                      </span>
                    ))}
                  </div>
                ) : null}

                {data && data.siblings.length ? (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="text-[12px] text-fade">同一件事还出现在</div>
                    <ul className="mt-2 space-y-2">
                      {data.siblings.map((s) => (
                        <li key={s.id}>
                          <a href={s.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-[13px] hover:underline">
                            <span className="h-[6px] w-[6px] rounded-full" style={{ background: platform(s.platform).tint }} />
                            <span className="text-muted">{platform(s.platform).label}</span>
                            <span className="clamp-2 flex-1">{s.title}</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="mt-6 flex gap-2">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-lg bg-ink text-[13px] font-medium text-white"
                  >
                    去 {platform(item.platform).label} 看原帖
                    <ExternalLink size={13} />
                  </a>
                  <button className="flex h-10 items-center justify-center gap-1.5 rounded-lg border border-line px-4 text-[13px] text-muted hover:border-ink/25 hover:text-ink">
                    <Heart size={14} />
                    收藏
                  </button>
                </div>
              </div>
            )}
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
