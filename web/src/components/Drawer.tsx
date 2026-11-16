import { AnimatePresence, motion } from "framer-motion";
import { Check, Copy, ExternalLink, Heart, MessageCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { getJSON, type CommentItem, type CommentsResponse, type FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { num, timeAgo } from "../format";

interface Detail {
  item: FeedItem;
  siblings: { id: string; platform: string; title: string; author: string; url: string; published_at: number }[];
}

const VIEW_LABEL: Record<string, string> = {
  video: "播放",
  article: "阅读",
  images: "浏览",
  short: "浏览",
  list: "热度",
};

function CommentBody({ comment }: { comment: CommentItem }) {
  const p = "#6b7280";
  return (
    <div className="flex gap-2.5">
      <span
        className="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-medium text-white"
        style={{ background: p }}
      >
        {(comment.author || "?").slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[12px]">
          <span className="truncate font-medium">{comment.author || "匿名"}</span>
          {comment.created_at ? <span className="text-[11px] text-fade">{timeAgo(comment.created_at)}</span> : null}
          {comment.like_count ? (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-fade">
              <Heart size={10} />
              {num(comment.like_count)}
            </span>
          ) : null}
        </div>
        <p className="mt-1 whitespace-pre-wrap text-[13px] leading-[1.75] text-muted">{comment.text}</p>
        {comment.replies?.length ? (
          <div className="mt-2 space-y-2 border-l border-line pl-3">
            {comment.replies.slice(0, 3).map((r) => (
              <div key={r.id}>
                <div className="text-[12px] font-medium">
                  {r.author || "匿名"}
                  {r.created_at ? <span className="ml-2 font-normal text-fade">{timeAgo(r.created_at)}</span> : null}
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-[12px] leading-[1.7] text-muted">{r.text}</p>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function Drawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [comments, setComments] = useState<CommentsResponse | null>(null);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [copied, setCopied] = useState(false);

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
    if (!id) {
      setComments(null);
      return;
    }
    let alive = true;
    setComments(null);
    setCommentsLoading(true);
    setCopied(false);
    getJSON<CommentsResponse>("/api/item/" + encodeURIComponent(id) + "/comments?limit=20")
      .then((d) => {
        if (alive) setComments(d);
      })
      .catch((err: Error) => {
        if (alive) setComments({ supported: true, items: [], count: 0, error: err.message });
      })
      .finally(() => {
        if (alive) setCommentsLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 抽屉打开时锁住背后的页面，不然滚轮会把下面的列表带着滚。
  useEffect(() => {
    if (!id) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [id]);

  const item = data?.item;
  const stats = item
    ? [
        { label: VIEW_LABEL[item.kind] ?? "浏览", value: item.view_count },
        { label: "点赞", value: item.like_count },
        { label: "评论", value: item.comment_count },
        { label: "分享", value: item.share_count },
      ].filter((s) => s.value > 0)
    : [];

  const copyLink = async () => {
    if (!item) return;
    try {
      await navigator.clipboard.writeText(item.url);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = item.url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <AnimatePresence>
      {id ? (
        <motion.div className="fixed inset-0 z-40" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/25" onClick={onClose} />
          <motion.aside
            className="absolute right-0 top-0 flex h-full w-full max-w-[480px] flex-col overflow-y-auto bg-white shadow-pop"
            initial={{ x: 40 }}
            animate={{ x: 0 }}
            exit={{ x: 40 }}
            transition={{ type: "tween", duration: 0.22 }}
          >
            {!item ? (
              <div className="flex h-full items-center justify-center text-[13px] text-fade">{error ? "加载失败：" + error : "加载中…"}</div>
            ) : (
              <div className="p-7">
                <div className="flex items-center gap-2 text-[12px] text-muted">
                  <span
                    className="inline-flex h-[18px] items-center rounded-full px-1.5 text-[11px] font-medium leading-none text-white"
                    style={{ background: platform(item.platform).tint }}
                  >
                    {platform(item.platform).label}
                  </span>
                  <span className="rounded border border-line px-1.5 py-0.5 text-[11px] text-fade">{KIND_LABEL[item.kind] ?? item.kind}</span>
                  <button onClick={onClose} className="ml-auto rounded-full p-1 text-fade hover:bg-wash hover:text-ink">
                    <X size={17} />
                  </button>
                </div>

                {data?.item.reasons?.length || (data?.item.cluster_size ?? 0) > 1 ? (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {(data?.item.reasons ?? []).slice(0, 3).map((r) => (
                      <span key={r} className="rounded-full border border-line bg-wash px-2 py-0.5 text-[11px] text-muted">
                        {r}
                      </span>
                    ))}
                    {(data?.item.cluster_size ?? 0) > 1 ? (
                      <span className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">
                        {data?.item.cluster_size} 个平台同题
                      </span>
                    ) : null}
                  </div>
                ) : null}

                <h2 className="mt-3 text-[21px] font-semibold leading-[1.4] tracking-tight">{item.title}</h2>
                <div className="mt-2 flex items-center gap-2 text-[12px] text-muted">
                  {item.author ? <span>{item.author}</span> : null}
                  {item.author && item.published_at ? <span className="text-fade">·</span> : null}
                  <span className="text-fade">{timeAgo(item.published_at)}</span>
                </div>

                {item.cover ? <img src={item.cover} alt="" referrerPolicy="no-referrer" className="mt-4 w-full rounded-lg object-cover" /> : null}

                {item.images.map((src) => (
                  <img key={src} src={src} alt="" referrerPolicy="no-referrer" className="mt-2 w-full rounded-lg object-cover" />
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

                {item.text ? <p className="mt-4 whitespace-pre-wrap text-[13px] leading-[1.85] text-muted">{item.text}</p> : null}

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
                  <button
                    onClick={() => void copyLink()}
                    className="flex h-10 items-center justify-center gap-1.5 rounded-lg border border-line px-4 text-[13px] text-muted hover:border-ink/25 hover:text-ink"
                  >
                    {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
                    {copied ? "已复制" : "复制链接"}
                  </button>
                </div>

                <section className="mt-6 border-t border-line pt-4">
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 text-[13px] font-semibold">
                      <MessageCircle size={13} className="text-muted" />
                      评论
                    </span>
                    {comments?.supported && comments.count > 0 ? (
                      <span className="text-[11px] text-fade">{comments.count} 条</span>
                    ) : null}
                    {comments?.from_cache ? <span className="text-[11px] text-fade">缓存</span> : null}
                  </div>

                  {commentsLoading ? (
                    <div className="mt-3 space-y-3">
                      {[0, 1, 2].map((i) => (
                        <div key={i} className="animate-pulse space-y-2">
                          <div className="h-3 w-1/4 rounded bg-wash" />
                          <div className="h-3 w-11/12 rounded bg-wash" />
                        </div>
                      ))}
                    </div>
                  ) : !comments ? null : !comments.supported ? (
                    <p className="mt-2 rounded-lg bg-wash px-3 py-2.5 text-[12px] leading-relaxed text-muted">
                      {comments.reason || "这个平台的插件没有提供评论接口"}
                    </p>
                  ) : comments.error ? (
                    <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-700">
                      评论没取到：{comments.error}
                    </p>
                  ) : comments.items.length === 0 ? (
                    <p className="mt-2 text-[12px] text-fade">暂时没取到评论。</p>
                  ) : (
                    <ul className="mt-3 space-y-4">
                      {comments.items.map((c) => (
                        <li key={c.id}>
                          <CommentBody comment={c} />
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            )}
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
