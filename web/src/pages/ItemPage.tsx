import DOMPurify from "dompurify";
import { ArrowLeft, Check, ChevronDown, Copy, ExternalLink, MessageCircle, RefreshCw, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  getDetail,
  getJSON,
  getSummary,
  type CommentItem,
  type CommentsResponse,
  type DetailMedia,
  type DetailPayload,
  type DetailResponse,
  type FeedItem,
  type SummaryResponse,
} from "../api";
import { CommentBody } from "../components/CommentBody";
import { runNavTransition } from "../navTransition";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface ItemResponse {
  item: FeedItem;
  siblings: { id: string; platform: string; title: string; author: string; url: string; published_at: number }[];
}

/** 评论区折叠时先放几条，剩下的点了「查看全部」再展开，滚到底继续翻页 */
const COLLAPSED_COMMENTS = 5;

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

/** 播放失败时的人话：<video> 的 onError 只给一个事件，用户看到的是一片黑。 */
function MediaBroken({ item, onRetry }: { item: FeedItem; onRetry: () => void }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-fade">
      <span>视频取不到了，直链可能过期。</span>
      <button onClick={onRetry} className="underline underline-offset-2 hover:text-ink">
        重试播放
      </button>
      <a href={item.url} target="_blank" rel="noreferrer noopener"
        className="underline underline-offset-2 hover:text-ink">
        去原帖看
      </a>
    </div>
  );
}

/** 点总结里的 [02:14]，B 站播放器用 t= 秒跳过去；别的平台没有统一参数，原样返回。 */
function withSeek(url: string, seek?: number | null) {
  if (seek == null || !url.includes("player.bilibili.com")) return url;
  try {
    const u = new URL(url);
    u.searchParams.set("t", String(Math.max(0, Math.floor(seek))));
    u.searchParams.set("autoplay", "1");
    return u.toString();
  } catch {
    return url;
  }
}

/** 媒体区：embed 走官方播放器，file 走直链（要 Referer 的走边车）。 */
function Media({ item, media, seek }: { item: FeedItem; media?: DetailMedia; seek?: number | null }) {
  const [direct, setDirect] = useState(false);
  // 直链过期时 <video> 只会静默失败（黑框），给一句人话 + 重试按钮，别让人以为页面坏了
  const [broken, setBroken] = useState(false);
  const [tick, setTick] = useState(0);
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
              key={tick}
              controls
              autoPlay
              preload="metadata"
              playsInline
              src={base + "/video"}
              poster={poster}
              className="h-full w-full"
              onError={() => setBroken(true)}
            />
          ) : (
            <iframe
              key={withSeek(media.embedUrl, seek)}
              src={withSeek(media.embedUrl, seek)}
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
        {direct && broken ? (
          <MediaBroken item={item} onRetry={() => { setBroken(false); setTick((t) => t + 1); }} />
        ) : null}
      </div>
    );
  }

  if (media.type === "file" && media.url) {
    const sidecar = Boolean(media.referer);
    return (
      <div className="mt-5">
        <div className="overflow-hidden rounded-xl border border-line bg-black">
          <video
            key={tick}
            controls
            preload="metadata"
            playsInline
            src={sidecar ? base + "/video" : media.url}
            poster={sidecar ? base + "/poster" : media.poster || undefined}
            className="max-h-[72vh] w-full"
            onError={() => setBroken(true)}
          />
        </div>
        {broken ? (
          <MediaBroken item={item} onRetry={() => { setBroken(false); setTick((t) => t + 1); }} />
        ) : null}
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

/** 秒数写成 2:14；一小时以上才补小时位 */
function clock(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const tail = String(s % 60).padStart(2, "0");
  return h ? h + ":" + String(m).padStart(2, "0") + ":" + tail : m + ":" + tail;
}

const BASIS_LABEL: Record<string, string> = {
  transcript: "完整字幕",
  official: "平台自带总结",
  desc: "标题与简介",
};

interface SummaryPanelProps {
  data: SummaryResponse | null;
  loading: boolean;
  error: string;
  /** 播放器能不能按秒跳（目前只有 B 站官方播放器认 t= 参数） */
  canSeek: boolean;
  onJump: (sec: number) => void;
  onRetry: () => void;
  url: string;
}

/** 详情页的默认视图：Agent 看完给的结论、要点和依据。 */
function SummaryPanel({ data, loading, error, canSeek, onJump, onRetry, url }: SummaryPanelProps) {
  if (loading) {
    return (
      <div className="mt-5 rounded-xl border border-line p-5">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <Sparkles size={13} />
          Agent 正在看这条内容…（大概十几秒）
        </div>
        <div className="mt-4 space-y-2.5">
          <div className="h-4 w-3/4 skeleton rounded" />
          <div className="h-3 w-full skeleton rounded" />
          <div className="h-3 w-11/12 skeleton rounded" />
          <div className="h-3 w-4/5 skeleton rounded" />
        </div>
      </div>
    );
  }

  const s = data?.summary;
  if (error || !data?.ok || !s) {
    return (
      <div className="mt-5 rounded-lg bg-wash px-3 py-2.5 text-[12px] leading-relaxed text-muted">
        {error || data?.error || "这条暂时总结不出来。"}
        <span className="mt-1.5 flex flex-wrap items-center gap-3">
          <button onClick={onRetry} className="underline underline-offset-2 hover:text-ink">再试一次</button>
          <a href={url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 hover:text-ink">
            去原站看
          </a>
        </span>
      </div>
    );
  }

  const basis = BASIS_LABEL[s.basis] || s.basis_text || "素材";
  const meta = [s.provider, s.model, s.ms ? (s.ms / 1000).toFixed(1) + "s" : ""].filter(Boolean).join(" · ");

  return (
    <div className="fade-in mt-5 rounded-xl border border-line p-5">
      <p className="text-[16px] font-medium leading-[1.7] tracking-tight">{s.tldr}</p>

      {s.points?.length ? (
        <ul className="mt-4 space-y-2.5">
          {s.points.map((point, index) => (
            <li key={index} className="flex gap-2.5 text-[14px] leading-[1.8] text-ink/90">
              {point.t != null && canSeek ? (
                <button
                  onClick={() => onJump(point.t as number)}
                  title="跳到播放器的这个位置"
                  className="mt-[3px] h-[19px] shrink-0 rounded bg-wash px-1.5 font-mono text-[11px] tabular-nums text-muted transition-colors hover:bg-solid hover:text-solid-fg"
                >
                  {clock(point.t)}
                </button>
              ) : point.t != null ? (
                <span className="mt-[3px] shrink-0 font-mono text-[11px] tabular-nums text-fade">{clock(point.t)}</span>
              ) : (
                <span className="mt-[9px] h-[4px] w-[4px] shrink-0 rounded-full bg-fade" />
              )}
              <span>{point.text}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {s.caveat ? (
        <p className="mt-4 text-[12px] leading-relaxed text-muted">注意：{s.caveat}</p>
      ) : null}
      {s.note ? <p className="mt-1.5 text-[12px] leading-relaxed text-fade">{s.note}</p> : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-3 text-[11px] text-fade">
        <span>依据 {basis}{s.source_chars ? " · " + s.source_chars + " 字" : ""}</span>
        {meta ? <span>{meta}</span> : null}
        <button onClick={onRetry} className="underline underline-offset-2 transition-colors hover:text-ink">
          重新总结
        </button>
        <a href={url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 transition-colors hover:text-ink">
          去原站
        </a>
      </div>
    </div>
  );
}

/** 详情页的过渡载体：铺满整页宽，卡片就是长大到它这里。 */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-[70vh] w-full" style={{ viewTransitionName: "of-card" }}>
      {children}
    </div>
  );
}

export default function ItemPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  // 返回时和进来时反着来：详情页缩回列表里那张卡片的位置与大小
  const goBack = () =>
    runNavTransition(
      () => navigate("/", { state: { vt: true, back: 1, fromId: item?.id } }),
      null,
      true,
    );
  const [data, setData] = useState<ItemResponse | null>(null);
  const [itemError, setItemError] = useState("");
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [comments, setComments] = useState<CommentsResponse | null>(null);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentNext, setCommentNext] = useState<string | null>(null);
  const [commentExpanded, setCommentExpanded] = useState(false);
  const [commentLoadingMore, setCommentLoadingMore] = useState(false);
  const commentSentinel = useRef<HTMLDivElement | null>(null);
  const [copied, setCopied] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [tab, setTab] = useState<"summary" | "source">("summary");
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  /** 点了总结里的时间戳之后，播放器要从这里开始 */
  const [seek, setSeek] = useState<number | null>(null);

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
    setCommentNext(null);
    setCommentExpanded(false);
    getJSON<CommentsResponse>("/api/item/" + encodeURIComponent(id) + "/comments?limit=20")
      .then((d) => {
        if (!alive) return;
        setComments(d);
        setCommentNext(d.next ?? null);
      })
      .catch((err: Error) => {
        if (alive) setComments({ supported: true, items: [], count: 0, next: null, error: err.message });
      })
      .finally(() => {
        if (alive) setCommentsLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setSummary(null);
    setSummaryError("");
    setSummaryLoading(true);
    getSummary(id)
      .then((d) => {
        if (alive) setSummary(d);
      })
      .catch((err: Error) => {
        if (alive) setSummaryError(err.message);
      })
      .finally(() => {
        if (alive) setSummaryLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  const retrySummary = useCallback(() => {
    if (!id) return;
    setSummaryLoading(true);
    setSummaryError("");
    getSummary(id, true)
      .then((d) => setSummary(d))
      .catch((err: Error) => setSummaryError(err.message))
      .finally(() => setSummaryLoading(false));
  }, [id]);

  const loadMoreComments = useCallback(() => {
    if (!id || !commentNext || commentLoadingMore) return;
    setCommentLoadingMore(true);
    getJSON<CommentsResponse>(
      "/api/item/" + encodeURIComponent(id) + "/comments?limit=20&cursor=" + encodeURIComponent(commentNext),
    )
      .then((d) => {
        setComments((prev) => {
          if (!prev) return d;
          const seen = new Set(prev.items.map((c) => c.id));
          const add = d.items.filter((c) => !seen.has(c.id));
          return { ...prev, supported: prev.supported, items: prev.items.concat(add) };
        });
        setCommentNext(d.next ?? null);
      })
      .catch(() => {
        // 翻页失败就当到底，把用户引回原站
        setCommentNext(null);
      })
      .finally(() => setCommentLoadingMore(false));
  }, [id, commentNext, commentLoadingMore]);

  /** 列表已经完整展示（没被折叠）或用户点了展开，尾部才需要显示「加载更多 / 就这些」 */
  const commentTailVisible = commentExpanded || (comments?.items.length ?? 0) <= COLLAPSED_COMMENTS;

  useEffect(() => {
    if (!commentTailVisible) return;
    const el = commentSentinel.current;
    if (!el || !commentNext) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMoreComments();
    }, { rootMargin: "240px" });
    io.observe(el);
    return () => io.disconnect();
  }, [commentTailVisible, commentNext, loadMoreComments]);

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
      <Shell>
      <div className="py-24 text-center">
        <p className="text-[15px] font-medium">这条内容打不开</p>
        <p className="mt-2 text-[13px] text-muted">{itemError}</p>
        <button
          type="button"
          onClick={goBack}
          className="mt-5 inline-block rounded-lg border border-line px-4 py-2 text-[13px] text-muted hover:text-ink"
        >
          回到信息流
        </button>
      </div>
      </Shell>
    );
  }

  if (!item) {
    return (
      <Shell>
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
      </Shell>
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
    <Shell>
    <div className="mx-auto max-w-[860px] pb-24 pt-6">
      <div className="flex items-center gap-3 text-[12px] text-muted">
        <button
          type="button"
          onClick={goBack}
          className="inline-flex items-center gap-1 rounded-full px-2 py-1 hover:bg-wash hover:text-ink"
        >
          <ArrowLeft size={13} />
          返回
        </button>
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

      <h1 className="rise mt-3 text-[26px] font-semibold leading-[1.35] tracking-tight">{item.title}</h1>
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

      <div className="mt-5 inline-flex items-center rounded-full border border-line p-0.5 text-[12px]">
        {([
          ["summary", "AI 总结"],
          ["source", "原文"],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            aria-pressed={tab === key}
            className={
              "rounded-full px-3 py-1 transition-colors duration-150 " +
              (tab === key ? "bg-solid text-solid-fg" : "text-muted hover:text-ink")
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "summary" ? (
        <SummaryPanel
          data={summary}
          loading={summaryLoading}
          error={summaryError}
          canSeek={Boolean(payload?.media?.embedUrl?.includes("player.bilibili.com"))}
          onJump={(sec) => {
            setSeek(sec);
            setTab("source");
          }}
          onRetry={retrySummary}
          url={item.url}
        />
      ) : null}

      {tab === "source" ? (
      <>
      {detailLoading ? (
        <div className="mt-5">
          {/* 只有真会有媒体（视频/图文/有封面）才占 16:9，文章类用小骨架，避免正文被推来推去 */}
          {item.kind === "video" || item.kind === "images" || item.cover ? (
            <div className="aspect-video skeleton rounded-xl" />
          ) : (
            <div className="h-16 skeleton rounded-xl" />
          )}
          <p className="mt-2 text-[12px] text-fade">正在取详情…（可能要十几秒）</p>
        </div>
      ) : (
        <div className="fade-in">
          <Media item={item} media={payload?.media} seek={seek} />
        </div>
      )}

      {detail?.supported === false ? (
        <p className="mt-5 rounded-lg bg-wash px-3 py-2.5 text-[12px] leading-relaxed text-muted">
          {detail.reason || "这个平台暂时只能在原站看。"}
        </p>
      ) : null}

      {detail?.error ? (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300">
          <span>详情没取到：{detail.error}</span>
          <button
            onClick={() => void refreshDetail()}
            className="inline-flex items-center gap-1 rounded-full border border-amber-300 dark:border-amber-500/35 px-2.5 py-1 text-[12px]"
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
            className={"fade-in mt-5 text-[14px] leading-[1.9] text-ink/90 [&_a]:text-[#1E80FF] [&_a]:underline [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-line [&_blockquote]:pl-3 [&_blockquote]:text-muted [&_code]:rounded [&_code]:bg-wash [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[13px] [&_h1]:mt-4 [&_h1]:text-[19px] [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-[17px] [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-[15px] [&_h3]:font-semibold [&_img]:my-3 [&_img]:max-w-full [&_img]:rounded-lg [&_li]:ml-5 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:mt-3 [&_p:has(>br:only-child)]:hidden [&_p.ztext-empty-paragraph]:hidden [&_figure]:my-3 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-wash [&_pre]:p-3 [&_table]:my-3 [&_td]:border [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-line [&_th]:px-2 [&_th]:py-1"}
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(body.value, { USE_PROFILES: { html: true } }) }}
          />
        ) : (
          <div className="mt-5 whitespace-pre-wrap text-[14px] leading-[1.9] text-ink/90">{body.value}</div>
        )
      ) : !detailLoading && detail?.supported !== false ? (
        item.text ? <p className="mt-5 whitespace-pre-wrap text-[14px] leading-[1.9] text-ink/90">{item.text}</p> : null
      ) : null}

      {payload?.note ? <p className="mt-4 text-[12px] leading-relaxed text-fade">{payload.note}</p> : null}
      </>
      ) : null}

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
            {comments.reason || "这个平台暂时读不到评论。"}
          </p>
        ) : comments.error ? (
          <p className="mt-2 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300">
            评论没取到：{comments.error}
          </p>
        ) : comments.items.length === 0 ? (
          <p className="mt-2 text-[12px] text-fade">暂时没取到评论。</p>
        ) : (
          <>
            <ul className="mt-3 space-y-4">
              {(commentExpanded ? comments.items : comments.items.slice(0, COLLAPSED_COMMENTS)).map((c: CommentItem) => (
                <li key={c.id}>
                  <CommentBody comment={c} />
                </li>
              ))}
            </ul>
            {!commentExpanded && comments.items.length > COLLAPSED_COMMENTS ? (
              <button
                type="button"
                onClick={() => setCommentExpanded(true)}
                className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg border border-line py-2.5 text-[12.5px] text-muted transition hover:bg-wash hover:text-ink"
              >
                查看更多评论（已取 {comments.items.length} 条）
                <ChevronDown size={13} />
              </button>
            ) : null}
            {commentTailVisible ? (
              <div ref={commentSentinel} className="mt-4">
                {commentLoadingMore ? (
                  <p className="py-2 text-center text-[12px] text-fade">正在取更多评论…</p>
                ) : commentNext ? (
                  <button
                    type="button"
                    onClick={loadMoreComments}
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-line py-2.5 text-[12.5px] text-muted transition hover:bg-wash hover:text-ink"
                  >
                    加载更多评论
                    <ChevronDown size={13} />
                  </button>
                ) : (
                  <p className="py-2 text-center text-[12px] leading-relaxed text-fade">
                    就这些了（已取 {comments.items.length} 条）。更多评论去{" "}
                    <a href={item.url} target="_blank" rel="noreferrer" className="text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                      {p.label}看原帖
                    </a>
                  </p>
                )}
              </div>
            ) : null}
          </>
        )}
      </section>

      <div className="mt-7 flex gap-2">
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-lg bg-solid text-[13px] font-medium text-solid-fg"
        >
          去 {p.label} 看原帖
          <ExternalLink size={13} />
        </a>
        <button
          onClick={() => void copyLink()}
          className="flex h-10 items-center justify-center gap-1.5 rounded-lg border border-line px-4 text-[13px] text-muted hover:border-ink/25 hover:text-ink"
        >
          {copied ? <Check size={14} className="text-emerald-600 dark:text-emerald-400" /> : <Copy size={14} />}
          {copied ? "已复制" : "复制链接"}
        </button>
      </div>

      {lightbox !== null && images[lightbox] ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setLightbox(null)}>
          <button className="absolute right-5 top-5 rounded-full bg-paper/10 p-2 text-white" onClick={() => setLightbox(null)}>
            <X size={18} />
          </button>
          <img src={images[lightbox]} alt="" referrerPolicy="no-referrer" className="max-h-full max-w-full object-contain" />
        </div>
      ) : null}
    </div>
    </Shell>
  );
}
