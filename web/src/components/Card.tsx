import type { CSSProperties } from "react";
import { motion } from "framer-motion";
import { FileText, Heart, Image as ImageIcon, MessageCircle, Play, Quote } from "lucide-react";
import type { FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface Props {
  item: FeedItem;
  /** 一起把被点的卡片元素交出去：跳页时要给它一个 view-transition-name */
  onOpen: (id: string, el: HTMLElement) => void;
  /** 从详情页返回时，给目标卡片挂上 of-card，让详情页缩回它的位置 */
  vtName?: string;
}

function hexAlpha(hex: string, alpha: number): string {
  return hex + Math.round(alpha * 255).toString(16).padStart(2, "0");
}

function ph(tint: string, fade = 0.72): CSSProperties {
  const grad = "linear-gradient(135deg, " + tint + " 0%, " + hexAlpha(tint, fade) + " 60%, " + hexAlpha(tint, 0.28) + " 100%)";
  return { ["--ph" as never]: grad } as CSSProperties;
}

/** 来源平台：实色小徽章，扫一眼就能分出是哪个站。 */
function PlatformBadge({ item }: { item: FeedItem }) {
  const p = platform(item.platform);
  return (
    <span
      className="inline-flex h-[18px] items-center rounded-full px-1.5 text-[11px] font-medium leading-none text-white"
      style={{ background: p.tint }}
      title={"来自 " + p.label}
    >
      {p.label}
    </span>
  );
}

/** 媒体位：所有卡片同一块地方、同一个比例，没有图也留位，整行才齐。 */
function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div data-media className="relative w-full aspect-video overflow-hidden rounded-lg bg-wash">
      {children}
    </div>
  );
}

function NoThumb({ item, label }: { item: FeedItem; label?: string }) {
  const p = platform(item.platform);
  const Icon = item.kind === "video" ? Play : item.kind === "images" ? ImageIcon : FileText;
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-1.5" style={{ background: hexAlpha(p.tint, 0.05) }}>
      <Icon size={16} className="text-fade" />
      <span className="text-[11px] tracking-wide text-fade">{label ?? "没有配图"}</span>
    </div>
  );
}

function Cover({ item }: { item: FeedItem }) {
  return (
    <Frame>
      <NoThumb item={item} />
      {item.cover ? (
        <img
          src={item.cover}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : null}
      {item.kind === "video" ? (
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black/35 backdrop-blur-sm">
            <Play size={14} className="ml-0.5 fill-white text-white" />
          </span>
        </span>
      ) : null}
      {item.duration ? (
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[11px] tabular-nums text-white">
          {duration(item.duration)}
        </span>
      ) : null}
    </Frame>
  );
}

function ImageGrid({ item }: { item: FeedItem }) {
  const pics = item.images.slice(0, 4);
  const cols = pics.length === 1 ? "grid-cols-1" : pics.length === 2 ? "grid-cols-2" : "grid-cols-3";
  return (
    <Frame>
      <div className={"grid h-full w-full gap-1 " + cols}>
        {pics.map((src, i) => (
          <div key={src + i} className="relative h-full w-full overflow-hidden rounded bg-wash">
            <NoThumb item={item} />
            <img
              src={src}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="absolute inset-0 h-full w-full object-cover"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
            {i === 3 && item.images.length > 4 ? (
              <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-[13px] text-white">
                +{item.images.length - 4}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      <span className="absolute left-1.5 top-1.5 rounded bg-black/45 px-1.5 py-0.5 text-[11px] tabular-nums text-white">
        {Math.max(1, item.images.length)} 图
      </span>
    </Frame>
  );
}

/** 榜单卡：编号交给媒体位，标题回到和其他卡同一个位置，不再挤在色块里。 */
function RankBand({ item }: { item: FeedItem }) {
  const p = platform(item.platform);
  const rank = Number((item.extra?.rank as number) ?? 0);
  return (
    <Frame>
      {/* ui-lint-ignore color-token — 整块是平台色渐变底，白字是对的 */}
      <div
        className="flex h-full w-full flex-col justify-between p-3.5"
        style={ph(p.tint)}
      >
        <span className="text-[52px] font-semibold leading-none tabular-nums text-white/90">
          {rank ? String(rank).padStart(2, "0") : "·"}
        </span>
        <div className="flex items-end justify-between gap-2">
          {/* ui-lint-ignore color-token */}
          <span className="text-[11px] tracking-wide text-white/70">热榜</span>
          {/* ui-lint-ignore color-token */}
          {item.text ? <span className="clamp-1 text-[13px] tabular-nums text-white/85">{item.text}</span> : null}
        </div>
      </div>
    </Frame>
  );
}

/** 纯文字动态：给一块同尺寸的文字面板，高度不再塌下去。 */
function TextPanel({ item, label }: { item: FeedItem; label?: string }) {
  const p = platform(item.platform);
  const text = (item.text || item.title || "").trim();
  return (
    <Frame>
      <div
        className="relative flex h-full w-full flex-col p-3.5"
        style={{ background: hexAlpha(p.tint, 0.06), border: "1px solid " + hexAlpha(p.tint, 0.14) }}
      >
        <Quote size={13} style={{ color: hexAlpha(p.tint, 0.75) }} className="shrink-0" />
        <p className="mt-1.5 flex-1 overflow-hidden pb-3 text-[13px] leading-[1.7] text-ink/75">{text}</p>
        {/* 文字按面板高度自适应，底部渐隐收口，不同列宽都不会留一块空白 */}
        <div
          className="pointer-events-none absolute inset-x-0 bottom-[22px] h-14"
          style={{ background: "linear-gradient(to top, " + hexAlpha(p.tint, 0.06) + ", transparent)" }}
        />
        <span className="relative text-[11px] text-fade">{(label ?? "文字动态") + " · " + p.label}</span>
      </div>
    </Frame>
  );
}

function Media({ item }: { item: FeedItem }) {
  if (item.kind === "list") return <RankBand item={item} />;
  if (item.kind === "short") return <TextPanel item={item} />;
  if (item.kind === "images" && item.images.length) return <ImageGrid item={item} />;
  // 长文/视频没有封面时，与其留一块「没有配图」，不如把摘要铺成文字面板（尺寸不变，行仍然齐）
  if (!item.cover && (item.kind === "article" || item.kind === "video")) {
    return <TextPanel item={item} label="摘要" />;
  }
  return <Cover item={item} />;
}

function excerpt(item: FeedItem): string {
  if (item.kind === "list" || item.kind === "short") return "";
  // 摘要已经铺在媒体位上的长文，下面不再重复一遍
  if (!item.cover && (item.kind === "article" || item.kind === "video")) return "";
  return (item.text ?? "").trim();
}

/** 没有正文可放时，这一行放「为什么给你看」，高度和正文摘要一致。 */
function MetaLine({ item, body }: { item: FeedItem; body: string }) {
  if (body) {
    return (
      <p className={"clamp-2 mt-1.5 h-[43px] shrink-0 text-[13px] leading-[1.65] text-muted " + (item.kind === "short" ? "border-l-2 border-line pl-2.5" : "")}>
        {body}
      </p>
    );
  }
  const reason = item.reasons?.[0] ?? "";
  const cluster = (item.cluster_size ?? 0) > 1 ? item.cluster_size + " 个平台同题" : "";
  const hint = reason || cluster || (item.kind === "short" || item.kind === "list"
    ? "点开详情"
    : !item.cover ? "点开看全文" : "");
  return (
    <p className={"clamp-2 mt-1.5 h-[43px] shrink-0 text-[12px] leading-[1.7] " + (hint ? "text-fade" : "")}>
      {hint || "\u00a0"}
    </p>
  );
}

export default function Card({ item, onOpen, vtName }: Props) {
  const p = platform(item.platform);
  const body = excerpt(item);
  const kindLabel = KIND_LABEL[item.kind] ?? item.kind;

  return (
    <motion.article
      role="button"
      tabIndex={0}
      aria-label={p.label + " · " + kindLabel + " · " + item.title}
      onClick={(e) => onOpen(item.id, e.currentTarget)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(item.id, e.currentTarget);
        }
      }}
      style={vtName ? { viewTransitionName: vtName } : undefined}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: "spring", stiffness: 420, damping: 34, mass: 0.7 }}
      className="group flex h-full min-h-[16rem] cursor-pointer flex-col rounded-card border border-line bg-paper p-3 text-left transition-colors hover:border-ink/25 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/20"
    >
      <header className="flex h-5 shrink-0 items-center gap-2 text-[11px]">
        <PlatformBadge item={item} />
        <span className="text-muted">{kindLabel}</span>
        {item.published_at ? <span className="ml-auto tabular-nums text-fade">{timeAgo(item.published_at)}</span> : null}
      </header>

      <div className="mt-2.5 shrink-0">
        <Media item={item} />
      </div>

      <h3 className="clamp-2 mt-2.5 h-[46px] shrink-0 text-[16px] font-semibold leading-[1.42] tracking-tight">{item.title}</h3>

      <MetaLine item={item} body={body} />

      <footer className="mt-auto flex items-center gap-1.5 pt-2.5 text-[12px] text-muted">
        {item.author_avatar ? (
          <img
            src={item.author_avatar}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-4 w-4 rounded-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <span className="flex h-4 w-4 items-center justify-center rounded-full text-[11px] font-medium text-white" style={{ background: p.tint }}>
            {(item.author || p.label).slice(0, 1)}
          </span>
        )}
        <span className="max-w-[52%] truncate text-[13px]">{item.author || p.label}</span>
        <span className="ml-auto flex items-center gap-2.5 text-fade">
          {item.like_count > 0 ? (
            <span className="flex items-center gap-1">
              <Heart size={11} />
              {num(item.like_count)}
            </span>
          ) : null}
          {item.comment_count > 0 ? (
            <span className="flex items-center gap-1">
              <MessageCircle size={11} />
              {num(item.comment_count)}
            </span>
          ) : null}
        </span>
      </footer>
    </motion.article>
  );
}
