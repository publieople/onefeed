import DOMPurify from "dompurify";
import { ArrowLeft, Check, Copy, ExternalLink, MessageCircle, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getDetail,
  getJSON,
  type CommentItem,
  type CommentsResponse,
  type DetailMedia,
  type DetailPayload,
  type DetailResponse,
  type FeedItem,
} from "../api";
import { CommentBody } from "../components/CommentBody";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface ItemResponse {
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

/** 统计标签：详情里的统计比列表更准，缺哪个就不显示哪个，不补 0。 */
function statCards(item: FeedItem, detail: DetailPayload | null) {
  const fromDetail = detail?.stats ?? {};
  const merged: Record<string, number> = {
    view: fromDetail.view || item.view_count,
    like: fromDetail.like || item.like_count,
    comment: fromDetail.comment || item.comment_count,
    share: fromDetail.share || item.share_count,
    collect: fromDetail.collect || 0,
    danmaku: fromDetail.danmaku || 0,
    answer: fromDetail.answer || 0,
  };
  const labels: Record<string, string> = {
    view: VIEW_LABEL[item.kind] ?? "浏览",
    like: "点赞",
    comment: "评论",
    share: "分享",
    collect: "收藏",
    danmaku: "弹幕",
    answer: "回答",
  };
  return Object.keys(merged)
    .filter((k) => merged[k] > 0)
    .map((k) => ({ key: k, label: labels[k] ?? k, value: merged[k] }));
}

/** 媒体区：embed 走官方播放器，file 走直链（要 Referer 的走边车）。 */
function Media({ item, media }: { item: FeedItem; media?: DetailMedia }) {
  const [direct, setDirect] = useState(false);
  if (!media) return null;
  const base = "/api/media/" + encodeURIComponent(item.id);

  if (media.type === "embed" && media.embedUrl) {
    // 官方播放器不是万能的（抖音 open.douyin.com 会挑 vid / 网络），插件给了直链就留个开关
    const canFallback = Boolean(media.fallbackUrl);
    const poster = media.poster ? base + "/poster" : undefined;
    return (
      <div className="mt-5">
        <div className="aspect-video overflow-hidden rounded-xl border border-line bg-black">
          {direct && canFallback ? (
            <video
              controls
              autoPlay
              preload="metadata"
              playsInline
              src={base + "/video"}
              poster={poster}
              className="h-full w-full"
            />
          ) : (
            <iframe
              src={media.embedUrl}
              title={item.title}
              className="h-full w-full"
              allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
              allowFullScreen
              referrerPolicy="no-referrer"
            />
          )}
        </div>
        {canFallback ? (
          <button
            onClick={() => setDirect((v) => !v)}
            className="mt-2 text-[12px] text-fade underline-offset-2 hover:text-ink hover:underline"
          >
            {direct ? "回到官方播放器" : "播放器打不开？换直链播放"}
          </button>
        ) : null}
      </div>
    );
  }

  if (media.type === "file" && media.url) {
    const sidecar = Boolean(media.referer);
    return (
      <div className="mt-5 overflow-hidden rounded-xl border border-line bg-black">
        <video
          controls
          preload="metadata"
          playsInline
          src={sidecar ? base + "/video" : media.url}
          poster={sidecar ? base + "/poster" : media.poster || undefined}
          className="max-h-[72vh] w-full"
        />
      </div>
    );
  }

  return null;
}

function Gallery({ images, onOpen }: { images: string[]; onOpen: (index: number) => void }) {
  if (!images.length) return null;
  // 单图不要占三列网格的第一格，居中给一张原比例大图
  if (images.length === 1) {
    return (
      <div className="mt-5">
        <button onClick={() => onOpen(0)} className="block overflow-hidden rounded-lg border border-line bg-wash">
          <img
            src={images[0]}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="max-h-[70vh] w-auto max-w-full object-contain"
          />
        </button>
      </div>
    );
  }
  return (
    <div className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-3">
      {images.map((src, index) => (
        <button
          key={src + index}
          onClick={() => onOpen(index)}
          className="relative aspect-[4/5] overflow-hidden rounded-lg border border-line bg-wash"
        >
          <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" />
        </button>
      ))}
    </div>
  );
}

export default function ItemPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<ItemResponse | null>(null);
  const [itemError, setItemError] = useState("");
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [comments, setComments] = useState<CommentsResponse | null>(null);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setData(null);
    setItemError("");
    getJSON<ItemResponse>("/api/item/" + encodeURIComponent(id))
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((err: Error) => {
        if (alive) setItemError(err.message);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setDetail(null);
    setDetailLoading(true);
    getDetail(id)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((err: Error) => {
        if (alive) setDetail({ supported: true, detail: null, error: err.message });
      })
      .finally(() => {
        if (alive) setDetailLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setComments(null);
    setCommentsLoading(true);
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

  const item = data?.item;
  useEffect(() => {
    if (item) document.title = item.title + " · OneFeed";
  }, [item]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightbox(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const stats = useMemo(() => (item ? statCards(item, detail?.detail ?? null) : []), [item, detail]);

  const refreshDetail = async () => {
    if (!id) return;
    setDetailLoading(true);
    try {
      setDetail(await getDetail(id, true));
    } catch (err) {
      setDetail({ supported: true, detail: null, error: (err as Error).message });
    } finally {
      setDetailLoading(false);
    }
  };

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

  if (itemError) {
    return (
      <div className="py-24 text-center">
        <p className="text-[15px] font-medium">这条内容打不开</p>
        <p className="mt-2 text-[13px] text-muted">{itemError}</p>
        <Link to="/" className="mt-5 inline-block rounded-lg border border-line px-4 py-2 text-[13px] text-muted hover:text-ink">
          回到信息流
        </Link>
      </div>
    );
  }

  if (!item) {
    return (
      <div className="mx-auto max-w-[860px] animate-pulse py-8">
        <div className="h-4 w-24 rounded bg-wash" />
        <div className="mt-5 h-8 w-3/4 rounded bg-wash" />
        <div className="mt-3 h-4 w-1/3 rounded bg-wash" />
        <div className="mt-6 aspect-video rounded-xl bg-wash" />
        <div className="mt-6 space-y-2">
          <div className="h-3 w-full rounded bg-wash" />
          <div className="h-3 w-11/12 rounded bg-wash" />
          <div className="h-3 w-4/5 rounded bg-wash" />
        </div>
      </div>
    );
  }

  const payload = detail?.detail ?? null;
  const body = payload?.body;
  // 详情里的图片走边车：xhscdn / 抖音图床都会看 Referer，浏览器自己带的是本地地址。
  const mediaBase = "/api/media/" + encodeURIComponent(item.id);
  const images = payload?.images?.length
    ? payload.images.map((_, index) => mediaBase + "/img-" + index)
    : item.images;
  const p = platform(item.platform);

  return (
    <div className="mx-auto max-w-[860px] pb-24 pt-6">
      <div className="flex items-center gap-3 text-[12px] text-muted">
        <Link to="/" className="inline-flex items-center gap-1 rounded-full px-2 py-1 hover:bg-wash hover:text-ink">
          <ArrowLeft size={13} />
          返回
        </Link>
        <span
          className="inline-flex h-[18px] items-center rounded-full px-1.5 text-[11px] font-medium leading-none text-white"
          style={{ background: p.tint }}
        >
          {p.label}
        </span>
        <span className="rounded border border-line px-1.5 py-0.5 text-[11px] text-fade">{KIND_LABEL[item.kind] ?? item.kind}</span>
        {item.duration ? <span className="text-fade">{duration(item.duration)}</span> : null}
        {(item.cluster_size ?? 0) > 1 ? (
          <span className="rounded-full bg-wash px-2 py-0.5 text-[11px]">{item.cluster_size} 个平台同题</span>
        ) : null}
      </div>

      <h1 className="mt-3 text-[26px] font-semibold leading-[1.35] tracking-tight">{item.title}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {item.author ? <span>{item.author}</span> : null}
        {item.author && item.published_at ? <span className="text-fade">·</span> : null}
        {item.published_at ? <span className="text-fade">{timeAgo(item.published_at)}</span> : null}
        {item.reasons?.length ? (
          <span className="ml-1 flex flex-wrap gap-1.5">
            {item.reasons.slice(0, 3).map((r) => (
              <span key={r} className="rounded-full border border-line bg-wash px-2 py-0.5 text-[11px]">
                {r}
              </span>
            ))}
          </span>
        ) : null}
      </div>

      {stats.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {stats.map((s) => (
            <div key={s.key} className="min-w-[86px] rounded-lg border border-line px-3 py-2">
              <div className="text-[15px] font-semibold tabular-nums">{num(s.value)}</div>
              <div className="text-[11px] text-fade">{s.label}</div>
            </div>
          ))}
        </div>
      ) : null}

      {detailLoading ? (
        <div className="mt-5">
          <div className="aspect-video animate-pulse rounded-xl bg-wash" />
          <p className="mt-2 text-[12px] text-fade">正在取详情…（小红书要开浏览器取一次，通常十几秒）</p>
        </div>
      ) : (
        <Media item={item} media={payload?.media} />
      )}

      {detail?.supported === false ? (
        <p className="mt-5 rounded-lg bg-wash px-3 py-2.5 text-[12px] leading-relaxed text-muted">
          {detail.reason || "这个平台的插件没有提供详情接口"}
        </p>
      ) : null}

      {detail?.error ? (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-700">
          <span>详情没取到：{detail.error}</span>
          <button
            onClick={() => void refreshDetail()}
            className="inline-flex items-center gap-1 rounded-full border border-amber-300 px-2.5 py-1 text-[12px]"
          >
            <RefreshCw size={11} />
            再试一次
          </button>
        </div>
      ) : null}

      {/* 视频笔记的 imageList 就是封面，已经在播放器里了，再铺一遍图会重复 */}
      {payload?.media && images.length <= 1 ? null : <Gallery images={images} onOpen={setLightbox} />}

      {body && body.value ? (
        body.kind === "html" ? (
          <div
            className={"mt-5 text-[14px] leading-[1.9] text-ink/90 [&_a]:text-[#1E80FF] [&_a]:underline [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-line [&_blockquote]:pl-3 [&_blockquote]:text-muted [&_code]:rounded [&_code]:bg-wash [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[13px] [&_h1]:mt-4 [&_h1]:text-[19px] [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-[17px] [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-[15px] [&_h3]:font-semibold [&_img]:my-3 [&_img]:max-w-full [&_img]:rounded-lg [&_li]:ml-5 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:mt-3 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-wash [&_pre]:p-3 [&_table]:my-3 [&_td]:border [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-line [&_th]:px-2 [&_th]:py-1"}
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(body.value, { USE_PROFILES: { html: true } }) }}
          />
        ) : (
          <div className="mt-5 whitespace-pre-wrap text-[14px] leading-[1.9] text-ink/90">{body.value}</div>
        )
      ) : !detailLoading && detail?.supported !== false ? (
        item.text ? <p className="mt-5 whitespace-pre-wrap text-[14px] leading-[1.9] text-ink/90">{item.text}</p> : null
      ) : null}

      {payload?.note ? <p className="mt-4 text-[12px] leading-relaxed text-fade">{payload.note}</p> : null}

      {item.tags?.length ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {item.tags.slice(0, 10).map((t) => (
            <span key={t} className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">
              #{t}
            </span>
          ))}
        </div>
      ) : null}

      {data && data.siblings.length ? (
        <section className="mt-7 border-t border-line pt-4">
          <div className="text-[12px] text-fade">同一件事还出现在</div>
          <ul className="mt-2 space-y-2">
            {data.siblings.map((s) => (
              <li key={s.id}>
                <Link to={"/item/" + encodeURIComponent(s.id)} className="flex items-center gap-2 text-[13px] hover:underline">
                  <span className="h-[6px] w-[6px] rounded-full" style={{ background: platform(s.platform).tint }} />
                  <span className="text-muted">{platform(s.platform).label}</span>
                  <span className="clamp-2 flex-1">{s.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-7 border-t border-line pt-4">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold">
            <MessageCircle size={13} className="text-muted" />
            评论
          </span>
          {comments?.supported && comments.count > 0 ? <span className="text-[11px] text-fade">{comments.count} 条</span> : null}
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
            {comments.items.map((c: CommentItem) => (
              <li key={c.id}>
                <CommentBody comment={c} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="mt-7 flex gap-2">
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-lg bg-ink text-[13px] font-medium text-white"
        >
          去 {p.label} 看原帖
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

      {lightbox !== null && images[lightbox] ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setLightbox(null)}>
          <button className="absolute right-5 top-5 rounded-full bg-white/10 p-2 text-white" onClick={() => setLightbox(null)}>
            <X size={18} />
          </button>
          <img src={images[lightbox]} alt="" referrerPolicy="no-referrer" className="max-h-full max-w-full object-contain" />
        </div>
      ) : null}
    </div>
  );
}
