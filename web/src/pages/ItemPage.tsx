import DOMPurify from "dompurify";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, Check, ChevronDown, Copy, ExternalLink, Heart, Loader2, MessageCircle, Radio, RefreshCw, Sparkles, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  addFavorite,
  getDetail,
  getJSON,
  peekItem,
  removeFavorite,
  streamSummary,
  SUMMARY_DEPTH_LABEL,
  type ItemResponse,
  type CommentItem,
  type CommentsResponse,
  type DetailMedia,
  type DetailPayload,
  type DetailResponse,
  type FeedItem,
  type SummaryDepth,
  type SummaryPoint,
  type SummaryPayload,
  type SummaryResponse,
} from "../api";
import type { OutletCtx } from "../App";
import { parseStreamText } from "../streamText";
import { CommentBody } from "../components/CommentBody";
import { confirmDialog } from "../components/ui/Confirm";
import { useAgentActions } from "../agent/AgentProvider";
import { useRailSlot } from "../layout/RailSlot";
import { createGhost } from "../motion/ghost";
import { DUR, EASE } from "../motion/tokens";
import { runNav } from "../motion/nav";
import { useModalScope } from "../motion/useModalScope";
import { useScrollLock } from "../motion/useScrollLock";
import { usePauseSidebarScroll } from "../motion/useSmoothWheelScroll";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

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
      <div>
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
              // 嵌的是第三方播放器：给它自己的一份源，别让它够到本站的 DOM / localStorage。
              // allow-same-origin + allow-scripts 是 B 站/抖音播放器能跑起来的最小组合。
              sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-forms"
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
      <div>
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

// 灯箱永远是深色遮罩，所以这里的白字 / 白底是刻意的，不走主题 token
/* ui-lint-ignore color-token */
const OVERLAY_HINT = "ml-3 text-white/45";
/* ui-lint-ignore color-token */
const OVERLAY_BTN = "rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20";
/* ui-lint-ignore color-token */
const OVERLAY_ARROW =
  "pointer-events-auto rounded-full bg-white/10 p-2.5 text-white transition-colors hover:bg-white/20";

/** 灯箱：铺满视口而不是铺满整页。点图切换「适应屏幕 / 原尺寸可滚动」，长图也能看 */
function Lightbox({
  images,
  index,
  onClose,
  onIndex,
}: {
  images: string[];
  index: number;
  onClose: () => void;
  onIndex: (next: number) => void;
}) {
  const [zoom, setZoom] = useState(false);
  // 灯箱铺满整页时，侧栏的滚轮惯性也该停下，背后的页面也不该还能滚
  usePauseSidebarScroll(true);
  useScrollLock(true);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => setZoom(false), [index]);
  const step = (delta: number) => onIndex((index + delta + images.length) % images.length);

  // 打开时锁住背后的页面滚动，并接上键盘：Esc 关、左右翻。
  // 同时压一层 dialog：灯箱盖着整页的时候，底下的 j/k、[、? 都不该再响应，
  // Tab 也只能在灯箱自己的按钮之间走。
  // 灯箱盖着整页时键盘只属于它：作用域由 hook 管，跟收藏框、确认框走同一套计数
  useModalScope(true);
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "Tab") {
        const nodes = Array.from(panelRef.current?.querySelectorAll<HTMLElement>("button") ?? []);
        if (!nodes.length) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && (active === first || !panelRef.current?.contains(active))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (back && document.body.contains(back)) back.focus?.();
    };
  }, [index, images.length]);
  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label="看图"
      className="fixed inset-0 z-[60] flex flex-col bg-black/90"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex shrink-0 items-center justify-between px-5 py-3 text-white/80">
        <span className="text-[12px] tabular-nums">
          {index + 1} / {images.length}
          <span className={OVERLAY_HINT}>{zoom ? "点图回到适应屏幕" : "点图看原尺寸"}</span>
        </span>
        <button
          ref={closeRef}
          aria-label="关闭"
          onClick={onClose}
          className={OVERLAY_BTN}
        >
          <X size={18} />
        </button>
      </div>
      <div
        className="flex-1 overflow-auto px-4 pb-6 md:px-10"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <img
          key={images[index]}
          src={images[index]}
          alt=""
          referrerPolicy="no-referrer"
          data-lb-image=""
          onClick={(e) => {
            e.stopPropagation();
            setZoom((v) => !v);
          }}
          className={
            zoom
              ? "mx-auto block w-[min(94vw,1200px)] max-w-none cursor-zoom-out"
              : "mx-auto block max-h-[calc(100dvh-96px)] max-w-full cursor-zoom-in object-contain"
          }
        />
      </div>
      {images.length > 1 ? (
        <div className="pointer-events-none absolute inset-y-0 left-0 right-0 flex items-center justify-between">
          <button
            aria-label="上一张"
            onClick={() => step(-1)}
            className={"ml-3 " + OVERLAY_ARROW}
          >
            <ChevronDown size={18} className="rotate-90" />
          </button>
          <button
            aria-label="下一张"
            onClick={() => step(1)}
            className={"mr-3 " + OVERLAY_ARROW}
          >
            <ChevronDown size={18} className="-rotate-90" />
          </button>
        </div>
      ) : null}
    </div>,
    document.body,
  );
}

function Gallery({
  images,
  onOpen,
}: {
  images: string[];
  onOpen: (index: number, el?: HTMLElement) => void;
}) {
  if (!images.length) return null;
  // 单图不要占三列网格的第一格，居中给一张原比例大图
  if (images.length === 1) {
    return (
      <div className="mt-5">
        <button
          type="button"
          data-lb-index={0}
          aria-label="看大图"
          onClick={(e) => onOpen(0, e.currentTarget)}
          className="block overflow-hidden rounded-lg border border-line bg-wash"
        >
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
          type="button"
          data-lb-index={index}
          aria-label={"看第 " + (index + 1) + " 张大图"}
          onClick={(e) => onOpen(index, e.currentTarget)}
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
  visual: "图片",
};

interface SummaryPanelProps {
  data: SummaryResponse | null;
  loading: boolean;
  error: string;
  /** 流式生成时已经收到的原始行协议文本 */
  streamRaw: string;
  /** 还在流：先渲染半成品，别让人盯着骨架屏 */
  streaming: boolean;
  /** thinking = 模型在通读素材，还没出正文 */
  phase: "thinking" | "writing" | "";
  /** 已经等了几秒 */
  seconds: number;
  /** 播放器能不能按秒跳（目前只有 B 站官方播放器认 t= 参数） */
  canSeek: boolean;
  onJump: (sec: number) => void;
  onRetry: () => void;
  url: string;
  /** 正在按哪一档重写：旧内容先留在原地，顶部盖一条进度 */
  busyDepth: SummaryDepth | "";
}

interface SummaryBodyProps {
  tldr: string;
  points: SummaryPoint[];
  caveat: string;
  canSeek: boolean;
  onJump: (sec: number) => void;
  /** 还在打字：末尾加一根闪烁光标 */
  live?: boolean;
}

/** 结论 + 要点 + 提醒。流式和非流式共用一套排版，收尾时不会发生「换了个长相」的跳动。 */
function SummaryBody({ tldr, points, caveat, canSeek, onJump, live }: SummaryBodyProps) {
  return (
    <>
      <p className="text-[16px] font-medium leading-[1.7] tracking-tight">
        {tldr}
        {live ? (
          <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] animate-pulse bg-ink/40 align-baseline" />
        ) : null}
      </p>

      {points.length ? (
        <ul className="mt-4 space-y-2.5">
          {points.map((point, index) => (
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

      {caveat ? <p className="mt-4 text-[12px] leading-relaxed text-muted">注意：{caveat}</p> : null}
    </>
  );
}

/** 详情页的默认视图：Agent 看完给的结论、要点和依据。 */
function SummaryPanel({
  data,
  loading,
  error,
  streamRaw,
  streaming,
  phase,
  seconds,
  canSeek,
  onJump,
  onRetry,
  url,
  busyDepth,
}: SummaryPanelProps) {
  const live = useMemo(() => parseStreamText(streamRaw), [streamRaw]);
  const s = data?.ok ? data.summary : undefined;
  const hasWords = Boolean(live.tldr || live.points.length);
  /**
   * 换档重写时旧的那份继续留在屏幕上：先清空再等八秒，版面会塌一下，比慢更难受。
   * 新字一到就顶上去，所以这里先取流式，没有再退回上一份 payload。
   */
  const body = hasWords
    ? { tldr: live.tldr, points: live.points, caveat: live.caveat }
    : s
      ? { tldr: s.tldr, points: s.points ?? [], caveat: s.caveat ?? "" }
      : null;
  const rewriting = Boolean(s) && streaming && !hasWords;

  if (!body && streaming) {
    return (
      <div className="fade-in mt-5 min-h-[164px] rounded-xl border border-line p-5">
        <div className="mb-3 flex items-center gap-2 text-[12px] text-muted">
          <Sparkles size={13} className="animate-pulse" />
          <span>{phase === "thinking" ? "Agent 正在通读素材…" : "Agent 正在看这条内容…"}</span>
          {seconds >= 1 ? (
            <span className="tabular-nums text-fade">{seconds.toFixed(0)}s</span>
          ) : null}
        </div>
        {hasWords ? (
          <SummaryBody
            tldr={live.tldr}
            points={live.points}
            caveat={live.caveat}
            canSeek={canSeek}
            onJump={onJump}
            live
          />
        ) : (
          <div className="space-y-2.5">
            <div className="h-4 w-3/4 skeleton rounded" />
            <div className="h-3 w-full skeleton rounded" />
            <div className="h-3 w-11/12 skeleton rounded" />
            <div className="h-3 w-4/5 skeleton rounded" />
          </div>
        )}
      </div>
    );
  }

  if (!body) {
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

  // 规则兜底且没有要点时，真正的内容只有标题；别再把它标成「AI 总结」，否则用户以为 AI 坏了。
  const rulesOnly = Boolean(s && s.engine === "rules" && !s.provider);
  if (rulesOnly && s && !s.points.length) {
    return (
      <div className="mt-5 rounded-xl border border-line p-5">
        <p className="text-[13px] leading-relaxed text-muted">
          还没有配置可用的 AI 模型，这条暂时只能显示标题：
          <span className="ml-1 text-ink">{s.tldr}</span>
        </p>
        <p className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
          <Link to="/settings" className="underline underline-offset-2 hover:text-ink">
            去设置添加模型
          </Link>
          <a href={url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 hover:text-ink">
            先去原站看
          </a>
        </p>
      </div>
    );
  }

  // body 可能来自流式半成品，这时还没有 payload：页脚一律按「有 payload 才渲染」来取值
  const basis = s ? BASIS_LABEL[s.basis] || s.basis_text || "素材" : "";
  const meta = s ? [s.provider, s.model, s.ms ? (s.ms / 1000).toFixed(1) + "s" : ""].filter(Boolean).join(" · ") : "";

  return (
    <div className="fade-in mt-5 rounded-xl border border-line p-5">
      {rulesOnly ? (
        <p className="mb-3 rounded-lg bg-wash px-2.5 py-1.5 text-[12px] leading-relaxed text-muted">
          这段要点由本地规则整理，还没有用 AI 模型；配好模型后会按「简洁 / 平衡 / 详细」重写。
        </p>
      ) : null}
      {rewriting ? (
        <div
          role="status"
          className="mb-3 flex items-center gap-2 rounded-lg bg-wash px-2.5 py-1.5 text-[12px] text-muted"
        >
          <Loader2 size={12} className="animate-spin" />
          <span>
            正在按「{SUMMARY_DEPTH_LABEL[(busyDepth || (s?.depth as SummaryDepth)) as SummaryDepth] ?? "这档"}」重写
            {phase === "thinking" ? "，先通读素材…" : "…"}
          </span>
          {seconds >= 1 ? <span className="tabular-nums text-fade">{seconds.toFixed(0)}s</span> : null}
        </div>
      ) : null}

      {error && body ? (
        <p className="mb-3 rounded-lg bg-danger/10 px-2.5 py-1.5 text-[12px] leading-relaxed text-danger">
          换档没成功：{error}，这里还是上一份。
          <button onClick={onRetry} className="ml-2 underline underline-offset-2">
            再试一次
          </button>
        </p>
      ) : null}

      <div className={rewriting ? "opacity-55 transition-opacity duration-200" : "transition-opacity duration-200"}>
        <SummaryBody
          tldr={body.tldr}
          points={body.points}
          caveat={body.caveat}
          canSeek={canSeek}
          onJump={onJump}
          live={hasWords && streaming}
        />
      </div>

      {s ? (
        <>
      {s.note ? <p className="mt-1.5 text-[12px] leading-relaxed text-fade">{s.note}</p> : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-3 text-[11px] text-fade">
        <span>
          依据 {basis}
          {s.source_chars ? " · " + s.source_chars + " 字" : ""}
          {s.images ? " · " + s.images + " 张图" : ""}
        </span>
        {meta ? <span>{meta}</span> : null}
        <button onClick={onRetry} className="underline underline-offset-2 transition-colors hover:text-ink">
          重新总结
        </button>
        <a href={url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 transition-colors hover:text-ink">
          去原站
        </a>
      </div>
        </>
      ) : null}
    </div>
  );
}

const DEPTH_ORDER: SummaryDepth[] = ["brief", "balanced", "detailed"];

function asDepth(value: unknown): SummaryDepth | "" {
  return value === "brief" || value === "balanced" || value === "detailed" ? value : "";
}

/** 三档粒度。选中态是一块滑过去的底，切换本身就是反馈；正在重写的那档带转圈。 */
function DepthSwitch({
  value,
  busy,
  onChange,
}: {
  value: SummaryDepth;
  busy: SummaryDepth | "";
  onChange: (depth: SummaryDepth) => void;
}) {
  const reduce = useReducedMotion();
  return (
    <div
      role="group"
      aria-label="总结粒度"
      className="inline-flex items-center rounded-full border border-line p-0.5 text-[12px]"
    >
      {DEPTH_ORDER.map((depth) => {
        const on = value === depth;
        return (
          <button
            key={depth}
            type="button"
            onClick={() => onChange(depth)}
            aria-pressed={on}
            title={depth === "brief" ? "只留骨架" : depth === "detailed" ? "写全，慢一点" : "默认"}
            className={
              "relative rounded-full px-2.5 py-1 transition-colors duration-150 " +
              (on ? "text-ink" : "text-muted hover:text-ink")
            }
          >
            {on ? (
              <motion.span
                layoutId="summary-depth-pill"
                className="absolute inset-0 rounded-full bg-wash ring-1 ring-inset ring-line"
                transition={reduce ? { duration: 0 } : { duration: DUR.base, ease: EASE }}
              />
            ) : null}
            <span className="relative flex items-center gap-1">
              {busy === depth ? <Loader2 size={10} className="animate-spin" /> : null}
              {SUMMARY_DEPTH_LABEL[depth]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** 详情页的容器。转场不再是「整张卡片放大成整页」，而是媒体框和标题各自长大，所以这里不挂名字。 */
function Shell({ children }: { children: React.ReactNode }) {
  return <div className="min-h-[70vh] w-full">{children}</div>;
}

export default function ItemPage({ ctx }: { ctx?: OutletCtx }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // 这条是 Agent 从对话里打开的：信息流里可能压根没有对应的卡片
  const fromAgent = Boolean((location.state as { fromAgent?: boolean } | null)?.fromAgent);
  // 返回时和进来时反着来：详情页缩回列表里那张卡片的位置与大小。
  // 回到进来时那一屏（带着筛选条件），而不是无条件回首页。
  const goBack = () => {
    const from = (location.state as { from?: string } | null)?.from || "/";
    // Agent 打开的条目没有卡片接它：给媒体框和标题挂一个右侧代位盒子当终点，
    // 视频才会缩回右侧（而不是整页淡出）。代位盒子挂在 apply 里 —— 只进新快照。
    const ghost = fromAgent ? createGhost({ media: true, title: true }) : null;
    runNav(
      "back",
      () => {
        ghost?.mount();
        navigate(from, { state: { vt: true, back: 1, fromId: item?.id, fromAgent } });
      },
      { after: () => ghost?.remove() },
    );
  };
  // 首屏垫底优先级：点卡片带过来的数据 > 悬停预取 > 空（骨架屏）。
  // 带过来的那份最关键：转场那 0.42s 里页面必须已经有媒体框和标题，
  // 否则新快照没有共享元素可以接，动画就退化成整页淡出——「只有打开过的卡片才有动效」就是这么来的。
  const seedItem = (location.state as { item?: FeedItem } | null)?.item ?? null;
  const seedData = (): ItemResponse | null => {
    const cached = peekItem(id)?.item;
    if (cached) return cached;
    return seedItem ? { item: seedItem, siblings: [] } : null;
  };
  const [data, setData] = useState<ItemResponse | null>(seedData);
  const [itemError, setItemError] = useState("");
  const [detail, setDetail] = useState<DetailResponse | null>(() => peekItem(id)?.detail ?? null);
  const [detailLoading, setDetailLoading] = useState(() => !peekItem(id)?.detail);
  const [comments, setComments] = useState<CommentsResponse | null>(null);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentsRetry, setCommentsRetry] = useState(0);
  const [commentNext, setCommentNext] = useState<string | null>(null);
  const [commentExpanded, setCommentExpanded] = useState(false);
  const [commentLoadingMore, setCommentLoadingMore] = useState(false);
  const commentSentinel = useRef<HTMLDivElement | null>(null);
  /** 转场结束后把焦点交给正文标题（卡片那个 <a> 已经随路由卸载） */
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const [copied, setCopied] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [tab, setTab] = useState<"summary" | "source">("summary");
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  /** 用户在这条上手动选的档位；空 = 跟着设置页的默认走 */
  const [depthChoice, setDepthChoice] = useState<SummaryDepth | "">("");
  /** 正在按哪一档重写（换档到首字之间） */
  const [busyDepth, setBusyDepth] = useState<SummaryDepth | "">("");
  /** 这条上刚看过的各档结果：切回去直接拿出来，不用再等一遍模型 */
  const depthCache = useRef<Partial<Record<SummaryDepth, SummaryPayload>>>({});
  /** 点了总结里的时间戳之后，播放器要从这里开始 */
  const [seek, setSeek] = useState<number | null>(null);
  /**
   * 收藏夹是独立功能：必须写一句备注，只记「为什么留」。
   * 卡片上那颗星是「稍后再看」，一键就进、不写备注，两边各存各的表。
   */
  const [favOpen, setFavOpen] = useState(false);
  const [fav, setFav] = useState<{ favorited: boolean; note: string } | null>(null);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    setData(seedData());
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

  // 换页之后焦点必须跟着走：卡片是个 <a>，路由一换它就卸载，焦点会掉回 body，
  // 键盘和读屏用户下一次 Tab 得从页头重新开始（View Transition 指南的强制项）。
  // 延后一拍，别和共享元素转场抢同一帧。
  useEffect(() => {
    const key = data?.item.id;
    if (!key) return;
    const timer = window.setTimeout(() => headingRef.current?.focus({ preventScroll: true }), 80);
    return () => window.clearTimeout(timer);
  }, [data?.item.id]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    const cached = peekItem(id)?.detail ?? null;
    setDetail(cached);
    setDetailLoading(!cached);
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
    const controller = new AbortController();
    // 有的平台评论要滚动抓十几秒；不设上限会让骨架一直转，先让用户看到「慢」而不是「坏」。
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setComments(null);
    setCommentsLoading(true);
    setCommentNext(null);
    setCommentExpanded(false);
    getJSON<CommentsResponse>("/api/item/" + encodeURIComponent(id) + "/comments?limit=20", controller.signal)
      .then((d) => {
        if (!alive) return;
        setComments(d);
        setCommentNext(d.next ?? null);
      })
      .catch((err: Error) => {
        if (!alive) return;
        const message = err.name === "AbortError" ? "评论加载较慢，已先显示其他内容；稍后可重试。" : err.message;
        setComments({ supported: true, items: [], count: 0, next: null, error: message });
      })
      .finally(() => {
        window.clearTimeout(timer);
        if (alive) setCommentsLoading(false);
      });
    return () => {
      alive = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [id, commentsRetry]);

  /* 总结走流式：先出 TLDR，再一条条出要点，比干等十几秒好受得多 */
  const summaryAlive = useRef(true);
  const summaryStop = useRef<(() => void) | null>(null);
  const streamStart = useRef(0);
  const [streamRaw, setStreamRaw] = useState("");
  /** 打字机已经铺出去的那一段。delta 是一次到达的，直接塞进 DOM 就是「一亮就是整篇」。 */
  const [shownRaw, setShownRaw] = useState("");
  const shownCount = useRef(0);
  const typeTimer = useRef<number | null>(null);
  const rawRef = useRef("");
  /** done 已经到达但字还没铺完的正稿：铺完再换上，不然会凭空跳成整篇 */
  const pendingSummary = useRef<SummaryResponse | null>(null);
  const [streaming, setStreaming] = useState(false);
  /** thinking = 模型在通读素材还没吐正文；writing = 已经在出字 */
  const [streamPhase, setStreamPhase] = useState<"thinking" | "writing" | "">("");
  const [streamSeconds, setStreamSeconds] = useState(0);

  /* 打字机铺完最后一段时，把等着的正稿换上去。
     直接一点就换会让版面从半篇跳成整篇，比慢更难受。 */
  const promoteSummary = useCallback(() => {
    const pending = pendingSummary.current;
    if (!pending) return;
    pendingSummary.current = null;
    setSummary(pending);
    setStreaming(false);
  }, []);

  const loadSummary = useCallback(
    (targetId: string, refresh: boolean, level: SummaryDepth | "" = "", keepOld = false) => {
    summaryStop.current?.();
    // 换档重写时保留旧内容（keepOld），版面不塌；换条目必须清空，否则会短暂显示上一条的总结
    if (!keepOld) setSummary(null);
    setSummaryError("");
    setSummaryLoading(true);
    setStreamRaw("");
    setShownRaw("");
    shownCount.current = 0;
    rawRef.current = "";
    pendingSummary.current = null;
    setStreamPhase("");
    setStreamSeconds(0);
    setStreaming(true);
    streamStart.current = typeof performance !== "undefined" ? performance.now() : Date.now();
    summaryStop.current = streamSummary(targetId, refresh, {
      onStatus: (phase) => {
        if (summaryAlive.current && phase === "thinking") setStreamPhase("thinking");
      },
      onDelta: (text) => {
        if (!summaryAlive.current) return;
        setStreamPhase("writing");
        // 同步写缓冲：delta 与 done 可能在同一轮事件里到达，onDone 要用最新长度判断
        rawRef.current += text;
        setStreamRaw(rawRef.current);
      },
      onDone: (payload) => {
      // 右栏「AI 总结」按这个广播刷新；总结是新生成的还是缓存命中都算一次更新
      window.dispatchEvent(new CustomEvent("onefeed:summary", { detail: { id: targetId } }));
        // 先记进缓存：切档来回时能立刻拿出来，不用再等模型
        const used = asDepth(payload.depth) || level;
        if (used) depthCache.current[used] = payload;
        setBusyDepth("");
        if (!summaryAlive.current) return;
        pendingSummary.current = { ok: true, summary: payload };
        setSummaryLoading(false);
        // 已经铺完了就立刻收；还有字没铺完，留给打字机收尾
        if (shownCount.current >= rawRef.current.length) promoteSummary();
      },
      onError: (message) => {
        setBusyDepth("");
        if (!summaryAlive.current) return;
        setSummaryError(message);
        setSummaryLoading(false);
        setStreaming(false);
      },
    }, level);
    },
    [],
  );

  useEffect(() => {
    summaryAlive.current = true;
    // 换条目等于换一份东西：缓存、手选档位、重写状态都得归零
    depthCache.current = {};
    setDepthChoice("");
    setBusyDepth("");
    if (id) loadSummary(id, false);
    return () => {
      summaryAlive.current = false;
      summaryStop.current?.();
      summaryStop.current = null;
    };
  }, [id, loadSummary]);

  const retrySummary = useCallback(() => {
    if (!id) return;
    summaryAlive.current = true;
    loadSummary(id, true, depthChoice);
  }, [id, loadSummary, depthChoice]);

  /** 当前生效的档位：手选 > 后端实际用的 > 设置页默认 > 平衡 */
  const effectiveDepth: SummaryDepth =
    depthChoice ||
    asDepth(summary?.summary?.depth) ||
    asDepth(ctx?.settings?.settings?.summary_depth) ||
    "balanced";

  /**
   * 换档。已经看过的档直接从本地拿（顺带一段淡入），没看过的才重新生成；
   * 重新生成期间旧内容不撤，顶部盖一条进度，版面不会先塌一下再长回来。
   */
  const switchDepth = useCallback(
    (next: SummaryDepth) => {
      if (!id || next === effectiveDepth) return;
      setDepthChoice(next);
      const cached = depthCache.current[next];
      if (cached) {
        summaryStop.current?.();
        summaryStop.current = null;
        pendingSummary.current = null;
        if (typeTimer.current !== null) {
          window.clearInterval(typeTimer.current);
          typeTimer.current = null;
        }
        rawRef.current = "";
        shownCount.current = 0;
        setStreamRaw("");
        setShownRaw("");
        setSummary({ ok: true, summary: cached, from_cache: true });
        setSummaryLoading(false);
        setStreaming(false);
        setSummaryError("");
        setBusyDepth("");
        return;
      }
      setBusyDepth(next);
      loadSummary(id, false, next, true);
    },
    [id, effectiveDepth, loadSummary],
  );

  /* delta 一次到达就是几十上百字，直接渲染等于「等几秒然后整篇弹出」。
     按字数匀速铺开：至少 56 字/秒，积压超过 1.2 秒的量就自动提速追平，
     既看得出在写，又不会让长文比模型还慢。用 setInterval 而不是 rAF —
     标签页不可见时 rAF 会被节流到近乎停摆，字就卡在半截。 */
  useEffect(() => {
    rawRef.current = streamRaw;
    if (typeTimer.current !== null) return;
    if (shownCount.current >= streamRaw.length) return;
    let last = typeof performance !== "undefined" ? performance.now() : Date.now();
    const tick = () => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      const dt = Math.max(0.016, Math.min(0.6, (now - last) / 1000));
      last = now;
      const target = rawRef.current;
      let n = shownCount.current;
      if (n < target.length) {
        const backlog = target.length - n;
        const rate = Math.max(60, backlog / 1.6);
        n = Math.min(target.length, n + Math.max(1, Math.round(rate * dt)));
        shownCount.current = n;
        setShownRaw(target.slice(0, n));
      }
      if (n >= rawRef.current.length && typeTimer.current !== null) {
        window.clearInterval(typeTimer.current);
        typeTimer.current = null;
        // 字铺完了：done 早就到的话，现在才换正稿
        promoteSummary();
      }
    };
    typeTimer.current = window.setInterval(tick, 50);
  }, [streamRaw, promoteSummary]);

  useEffect(
    () => () => {
      if (typeTimer.current !== null) {
        window.clearInterval(typeTimer.current);
        typeTimer.current = null;
      }
    },
    [],
  );

  /* 等待秒数要走字：模型先想七八秒才开口，有个数字在动，用户才知道没卡死 */
  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      setStreamSeconds((now - streamStart.current) / 1000);
    }, 250);
    return () => window.clearInterval(timer);
  }, [streaming]);

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

  /* 告诉 Agent「我在看哪一条」：右栏点「总结这一条」不用再问你指谁。
     离开详情页要清掉，否则在信息流里问「总结这条」会指向上一条。 */
  const { setFocus, openWith } = useAgentActions();
  useEffect(() => {
    if (!item) return;
    setFocus({ id: item.id, title: item.title, platform: item.platform });
    return () => setFocus(null);
  }, [item?.id, item?.title, item?.platform, setFocus]);

  /* 右栏槽位的「同题」页签：右栏挂在外壳上，取不到这份数据，得从这儿递过去 */
  const { setSiblings } = useRailSlot();
  useEffect(() => {
    setSiblings(
      (data?.siblings ?? []).map((sib) => ({ id: sib.id, platform: sib.platform, title: sib.title })),
    );
    return () => setSiblings([]);
  }, [data?.siblings, setSiblings]);

  // 点缩略图：图从缩略图的位置长成整屏大图，关掉时再缩回去。
  // 缩略图和灯箱大图会同时存在于 DOM 里，名字不能常驻在 img 上：
  // 旧快照挂缩略图，apply 之后把名字交给新挂载的大图，两端才各有一个 of-lb。
  const openLightbox = useCallback((index: number, el?: HTMLElement) => {
    if (!el) {
      setLightbox(index);
      return;
    }
    runNav("lightbox", () => setLightbox(index), {
      names: [{ el, name: "of-lb" }],
      afterApply: () => {
        el.style.viewTransitionName = "";
        const img = document.querySelector<HTMLElement>("[data-lb-image]");
        if (img) img.style.viewTransitionName = "of-lb";
      },
      after: () => {
        el.style.viewTransitionName = "";
        const img = document.querySelector<HTMLElement>("[data-lb-image]");
        if (img) img.style.viewTransitionName = "";
      },
    });
  }, []);
  const closeLightbox = useCallback((index: number) => {
    const thumb = document.querySelector<HTMLElement>('[data-lb-index="' + index + '"]');
    const img = document.querySelector<HTMLElement>("[data-lb-image]");
    // 关闭是反向：走 back 这一组，CSS 才会让大图快照留在场上缩回去
    runNav("back", () => setLightbox(null), {
      names: img ? [{ el: img, name: "of-lb" }] : [],
      // 大图已经卸载，这时才能把名字交给缩略图；两端同时挂名会被浏览器当成重名
      afterApply: () => {
        if (thumb) thumb.style.viewTransitionName = "of-lb";
      },
      after: () => {
        if (thumb) thumb.style.viewTransitionName = "";
      },
    });
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
  const favorited = fav ? fav.favorited : Boolean(item.favorited);
  const favNote = fav ? fav.note : item.favorite_note ?? "";

  // hero 里的那一块就是共享元素的落点。列表里只有图文的卡片没有视频位，
  // 图文（kind=images）继续走下面的画廊，不额外顶一块 hero，免得同一张图出现两次。
  const heroMedia = payload?.media ?? null;
  const heroCover = !heroMedia && item.kind !== "images" ? item.cover ?? null : null;
  const showHero = Boolean(heroMedia) || Boolean(heroCover) || item.kind === "video";

  return (
    <Shell>
    <div className="pt-6">
    <div className="mx-auto max-w-[860px] pb-24">
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

      {/* 标题是第二块共享元素：从卡片里那两行小标题长成正文标题 */}
      {/* 焦点落点：tabindex=-1 让它可编程聚焦但不进 Tab 序列；outline-none 是不给程序
          聚焦画框（键盘用户打开页面后仍按 Tab 继续走，位置由转场本身交代） */}
      <h1
        ref={headingRef}
        tabIndex={-1}
        data-vt="title"
        style={{ viewTransitionName: "of-title" }}
        className="mt-3 font-display text-[26px] font-semibold leading-[1.35] tracking-tight outline-none"
      >
        {item.title}
      </h1>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {item.author && item.author_id ? (
          <Link
            to={"/author/" + encodeURIComponent(item.platform) + "/" + encodeURIComponent(item.author_id)}
            state={{ from: location.pathname + location.search }}
            className="rounded transition hover:text-ink"
            title="看作者主页"
          >
            {item.author}
          </Link>
        ) : item.author ? (
          <span>{item.author}</span>
        ) : null}
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

      {item.is_live ? (
        <div className="mt-4 rounded-xl border border-line bg-wash/45 px-4 py-3 text-[12.5px] leading-relaxed text-muted">
          <div className="flex items-center gap-1.5 font-medium text-ink">
            <Radio size={13} />
            这是直播动态，不会进信息流
          </div>
          <p className="mt-1">
            直播结束后没有可读的正文，所以它只在历史记录里留个位置。想看这个人的其他内容，点上面的作者名。
          </p>
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-accent hover:underline">
              去 B 站看这条动态 <ExternalLink size={11} />
            </a>
          ) : null}
        </div>
      ) : null}

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

      {/* 媒体区常驻在 tab 之上：既是共享元素「长大」的落点，也避免每次切 tab 都重新挂载播放器把进度清零 */}
      {showHero ? (
        <div data-vt="media" style={{ viewTransitionName: "of-media" }} className="mt-5">
          {heroMedia ? (
            <Media item={item} media={heroMedia} seek={seek} />
          ) : detailLoading ? (
            <div className="aspect-video skeleton rounded-xl" />
          ) : heroCover ? (
            <img
              src={heroCover}
              alt=""
              referrerPolicy="no-referrer"
              className="max-h-[70vh] w-full rounded-xl border border-line bg-wash object-contain"
            />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-xl bg-wash text-[12px] text-fade">
              这个平台暂时没法内嵌播放，用下面的按钮去原站看
            </div>
          )}
        </div>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="inline-flex items-center rounded-full border border-line p-0.5 text-[12px]">
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
        {/* 粒度只影响 AI 总结，跟着 tab 一起摆在顺手的位置；换档就重写，不用回设置页 */}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-fade">总结粒度</span>
          <DepthSwitch value={effectiveDepth} busy={busyDepth} onChange={switchDepth} />
        </div>
      </div>

      {tab === "summary" ? (
        <div key="summary" className="rise">
        <SummaryPanel
          data={summary}
          loading={summaryLoading}
          error={summaryError}
          streamRaw={shownRaw}
          streaming={streaming}
          phase={streamPhase}
          seconds={streamSeconds}
          canSeek={Boolean(payload?.media?.embedUrl?.includes("player.bilibili.com"))}
          onJump={(sec) => {
            setSeek(sec);
            setTab("source");
          }}
          onRetry={retrySummary}
          url={item.url}
          busyDepth={busyDepth}
        />
        {/* 就这一条继续问：全站只有一个 Agent，这里只负责把「在问哪条」带过去，
            不再自带一套对话状态（两套历史各记各的，谁也接不上谁）。 */}
        <section className="mt-5 rounded-xl border border-line px-4 py-3.5" aria-label="就这条内容问 Agent">
          <div className="flex items-center gap-2">
            <MessageCircle size={13} className="text-muted" />
            <span className="text-[12.5px] font-medium">问问这条</span>
            <span className="text-[11px] text-fade">带上这条的标题、正文和总结，接着聊</span>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {["最值得记住的是哪一点", "有什么没讲清的地方", "这条和同题其他平台说法一样吗"].map((text) => (
              <button
                key={text}
                type="button"
                onClick={() => openWith(text)}
                className="rounded-full border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-ink/25 hover:text-ink"
              >
                {text}
              </button>
            ))}
            <button
              type="button"
              onClick={() => openWith("")}
              className="ml-auto inline-flex items-center gap-1 rounded-full bg-solid px-3 py-1 text-[12px] text-solid-fg transition-transform active:scale-95"
            >
              打开 Agent
            </button>
          </div>
        </section>
        </div>
      ) : null}

      {tab === "source" ? (
      <div key="source" className="rise">
      <>
      {detailLoading ? (
        <p className="mt-5 text-[12px] text-fade">正在取正文与评论…（可能要十几秒）</p>
      ) : null}

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
      {payload?.media && images.length <= 1 ? null : <Gallery images={images} onOpen={openLightbox} />}

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
      </div>
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
                <Link
                  to={"/item/" + encodeURIComponent(s.id)}
                  state={{ from: (location.state as { from?: string } | null)?.from || "/" }}
                  className="flex items-center gap-2 text-[13px] hover:underline"
                >
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
          <div className="mt-2 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300">
            <span>评论没取到：{comments.error}</span>
            <button
              type="button"
              onClick={() => setCommentsRetry((n) => n + 1)}
              className="ml-2 underline underline-offset-2 hover:text-ink"
            >
              重试
            </button>
          </div>
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
        <button
          type="button"
          onClick={() => setFavOpen(true)}
          aria-pressed={favorited}
          className={
            "flex h-10 items-center justify-center gap-1.5 rounded-lg border px-4 text-[13px] transition " +
            (favorited
              ? "border-accent/40 bg-wash text-accent"
              : "border-line text-muted hover:border-ink/25 hover:text-ink")
          }
        >
          <Heart size={14} fill={favorited ? "currentColor" : "none"} />
          {favorited ? "已收藏" : "收藏"}
        </button>
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

      {favOpen ? (
        <FavoriteDialog
          itemId={item.id}
          title={item.title}
          favorited={favorited}
          note={favNote}
          onClose={() => setFavOpen(false)}
          onChange={(next) => {
            setFav(next);
            setFavOpen(false);
          }}
        />
      ) : null}

      {lightbox !== null && images[lightbox] ? (
        <Lightbox
          images={images}
          index={lightbox}
          onClose={() => closeLightbox(lightbox)}
          onIndex={setLightbox}
        />
      ) : null}
    </div>
    </div>
    </Shell>
  );
}

const DIALOG_FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * 收藏对话框。收藏和「稍后再看」是两件事，所以这里强制写一句备注：
 * 三天后回来看「收藏夹」，只有一句自己写的话才能提醒当初为什么留下它。
 * 已收藏时同一个框兼作编辑：改备注、或移出（移出还要过一次确认）。
 */
function FavoriteDialog({
  itemId,
  title,
  favorited,
  note,
  onClose,
  onChange,
}: {
  itemId: string;
  title: string;
  favorited: boolean;
  note: string;
  onClose: () => void;
  onChange: (next: { favorited: boolean; note: string }) => void;
}) {
  const [value, setValue] = useState(note);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState("");
  const panelRef = useRef<HTMLDivElement | null>(null);
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const restoreRef = useRef<Element | null>(null);
  const busy = saving || removing;
  const canSave = value.trim().length > 0 && !busy;

  useScrollLock(true);
  // 收藏框是弹窗，就得压住底下的全局键：之前漏了这一行，开着它按 [ 会收起左栏、
  // 按 t 会切主题、按 ? 还会在它上面再叠一层帮助（实测 dialog 1→2）。
  useModalScope(true);

  useEffect(() => {
    restoreRef.current = document.activeElement;
    requestAnimationFrame(() => areaRef.current?.focus());
    const back = restoreRef.current as HTMLElement | null;
    return () => {
      // 焦点还给「收藏」按钮：关掉之后键盘用户不该落回 body。
      // 同步还，不等 rAF —— 后台标签页里 rAF 会被节流到 1 秒一次，实测焦点要 414ms 才回来。
      if (back && document.body.contains(back)) back.focus?.();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const nodes = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE) ?? []).filter(
        (n) => n.offsetParent !== null,
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || !panelRef.current?.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const save = async () => {
    const text = value.trim();
    if (!text || busy) return;
    setSaving(true);
    setError("");
    try {
      const res = await addFavorite(itemId, text);
      window.dispatchEvent(new CustomEvent("onefeed:favorites"));
      const wasFavorited = favorited;
      window.dispatchEvent(
        new CustomEvent("onefeed:toast", { detail: { text: wasFavorited ? "已更新备注" : "已收进收藏夹" } }),
      );
      onChange({ favorited: true, note: res.favorite?.note || text });
    } catch (err) {
      setError((err as Error).message || "没存上，稍后再试。");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (busy) return;
    const ok = await confirmDialog({
      title: "移出收藏夹？",
      body: "这条记录和备注会一起删掉。卡片上的「稍后再看」不受影响。",
      confirmText: "移出",
      tone: "danger",
    });
    if (!ok) return;
    setRemoving(true);
    setError("");
    try {
      await removeFavorite(itemId);
      window.dispatchEvent(new CustomEvent("onefeed:favorites"));
      window.dispatchEvent(new CustomEvent("onefeed:toast", { detail: { text: "已移出收藏夹" } }));
      onChange({ favorited: false, note: "" });
    } catch (err) {
      setError((err as Error).message || "没移出，稍后再试。");
    } finally {
      setRemoving(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-solid/25 backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={favorited ? "编辑收藏" : "收藏这条"}
        className="relative w-full max-w-[440px] rounded-card border border-line bg-paper p-5 shadow-pop"
      >
        <h2 className="text-[16px] font-semibold text-ink">{favorited ? "编辑收藏" : "收藏这条"}</h2>
        <p className="mt-1 line-clamp-1 text-[12px] text-fade">{title}</p>
        <label className="mt-4 block">
          <span className="text-[12px] text-muted">为什么留下它？（一句话就够，以后靠它回忆）</span>
          <textarea
            ref={areaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={3}
            maxLength={200}
            placeholder="比如：讲清了 C 端 AI 定价的三层成本，写方案时能引用"
            className="mt-1.5 w-full resize-none rounded-lg border border-line bg-wash px-3 py-2 text-[13px] leading-relaxed text-ink outline-none focus-visible:ring-2 focus-visible:ring-ink/25"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void save();
              }
            }}
          />
        </label>
        <div className="mt-1 flex items-center justify-between text-[11px] text-fade">
          <span>{error ? <span className="text-danger">{error}</span> : "⌘/Ctrl + Enter 保存"}</span>
          <span className="tabular-nums">{value.trim().length}/200</span>
        </div>
        <div className="mt-4 flex items-center gap-2">
          {favorited ? (
            <button
              type="button"
              onClick={() => void remove()}
              disabled={busy}
              className="flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-[13px] text-muted transition hover:border-danger/40 hover:text-danger disabled:opacity-50"
            >
              <Trash2 size={13} />
              {removing ? "移出中…" : "移出收藏夹"}
            </button>
          ) : null}
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-9 rounded-full border border-line px-4 text-[13px] text-ink hover:bg-wash"
            >
              取消
            </button>
            <button
              type="button"
              disabled={!canSave}
              onClick={() => void save()}
              className="h-9 rounded-full bg-solid px-4 text-[13px] font-medium text-solid-fg disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
