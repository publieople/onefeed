import type { CSSProperties } from "react";
import { FileText, Heart, Image as ImageIcon, MessageCircle, Play } from "lucide-react";
import type { FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface Props {
  item: FeedItem;
  onOpen: (id: string) => void;
}

function hexAlpha(hex: string, alpha: number): string {
  return hex + Math.round(alpha * 255).toString(16).padStart(2, "0");
}

function ph(tint: string, fade = 0.72): CSSProperties {
  const grad = "linear-gradient(135deg, " + tint + " 0%, " + hexAlpha(tint, fade) + " 60%, " + hexAlpha(tint, 0.28) + " 100%)";
  return { ["--ph" as never]: grad } as CSSProperties;
}

function PlatformTag({ item }: { item: FeedItem }) {
  const p = platform(item.platform);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-1.5 py-[2px] text-[10.5px] font-medium leading-none"
      style={{ color: p.tint, borderColor: hexAlpha(p.tint, 0.28), background: hexAlpha(p.tint, 0.07) }}
      title={"来自 " + p.label}
    >
      <span className="h-[5px] w-[5px] rounded-full" style={{ background: p.tint }} />
      {p.label}
    </span>
  );
}

/** 没有封面 / 封面加载失败时的占位：一眼能看出「这里本来就没图」，不像坏图。 */
function NoThumb({ item, className = "" }: { item: FeedItem; className?: string }) {
  const p = platform(item.platform);
  const Icon = item.kind === "video" ? Play : item.kind === "images" ? ImageIcon : FileText;
  return (
    <div
      className={"flex h-full w-full flex-col items-center justify-center gap-1.5 border border-dashed border-line bg-wash " + className}
    >
      <Icon size={16} className="text-fade" />
      <span className="text-[10.5px] tracking-wide text-fade">无封面 · {p.label}</span>
    </div>
  );
}

function Cover({ item, rounded = "rounded-lg" }: { item: FeedItem; rounded?: string }) {
  return (
    <div className={"relative w-full aspect-video overflow-hidden " + rounded + " bg-wash"}>
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
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[11px] text-white">
          {duration(item.duration)}
        </span>
      ) : null}
      {item.kind === "images" ? (
        <span className="absolute left-1.5 top-1.5 rounded bg-black/45 px-1.5 py-0.5 text-[11px] text-white">
          {Math.max(1, item.images.length)} 图
        </span>
      ) : null}
    </div>
  );
}

function ImageGrid({ item }: { item: FeedItem }) {
  const pics = item.images.slice(0, 4);
  const cols = pics.length === 1 ? "grid-cols-1" : pics.length === 2 ? "grid-cols-2" : "grid-cols-3";
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-wash">
      <div className={"grid h-full w-full gap-1 " + cols}>
        {pics.map((src, i) => (
          <div key={src + i} className="relative h-full w-full overflow-hidden rounded-[4px] bg-wash">
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
      <span className="absolute left-1.5 top-1.5 rounded bg-black/45 px-1.5 py-0.5 text-[11px] text-white">
        {Math.max(1, item.images.length)} 图
      </span>
    </div>
  );
}

function RankBand({ item }: { item: FeedItem }) {
  const rank = Number((item.extra?.rank as number) ?? 0);
  return (
    <div className="relative flex h-[112px] w-full items-center gap-4 overflow-hidden rounded-lg px-4" style={ph(platform(item.platform).tint)}>
      <span className="text-[38px] font-semibold leading-none tabular-nums text-white/85">
        {rank ? String(rank).padStart(2, "0") : "·"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] tracking-wide text-white/70">{platform(item.platform).label} · 榜单</div>
        <div className="mt-1 clamp-2 text-[15px] font-medium leading-[1.4] text-white">{item.title}</div>
      </div>
      {item.text ? <span className="shrink-0 self-end pb-1 text-[11px] text-white/80">{item.text}</span> : null}
    </div>
  );
}

function Media({ item }: { item: FeedItem }) {
  if (item.kind === "list") return <RankBand item={item} />;
  if (item.kind === "short") return null;
  if (item.images.length) return <ImageGrid item={item} />;
  if (item.kind === "video") return <Cover item={item} />; // 没封面也留位置，卡片高度才一致
  if (item.cover) return <Cover item={item} />;
  return null;
}

function excerpt(item: FeedItem): string {
  if (item.kind === "list") return "";
  const text = (item.text ?? "").trim();
  if (!text) return "";
  if (item.kind === "short") return text;
  return text.length > 0 ? text : "";
}

function Reasons({ item }: { item: FeedItem }) {
  if (!item.reasons?.length && !item.cluster_size) return null;
  const chips = [...(item.reasons ?? [])].slice(0, 2);
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {chips.map((r) => (
        <span key={r} className="rounded-full border border-line bg-white px-2 py-0.5 text-[11px] text-muted">
          {r}
        </span>
      ))}
      {item.cluster_size > 1 ? (
        <span className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">{item.cluster_size} 个平台同题</span>
      ) : null}
    </div>
  );
}

export default function Card({ item, onOpen }: Props) {
  const p = platform(item.platform);
  const body = excerpt(item);

  return (
    <article
      onClick={() => onOpen(item.id)}
      className="group flex cursor-pointer flex-col rounded-card border border-line bg-white p-3 transition hover:border-ink/20 hover:shadow-sm"
    >
      <header className="flex items-center gap-1.5 text-[11px] text-fade">
        <PlatformTag item={item} />
        <span>{KIND_LABEL[item.kind] ?? item.kind}</span>
        {item.published_at ? <span className="ml-auto tabular-nums">{timeAgo(item.published_at)}</span> : <span className="ml-auto">{p.label}</span>}
      </header>

      <div className="mt-2.5">
        <Media item={item} />
      </div>

      {item.kind !== "list" ? (
        <h3 className={"clamp-2 text-[16px] font-semibold leading-[1.42] tracking-tight " + (item.kind === "short" || !item.cover ? "mt-0.5" : "mt-2.5")}>
          {item.title}
        </h3>
      ) : null}

      {body ? (
        <p className={"clamp-2 mt-1.5 text-[12.5px] leading-[1.65] text-muted " + (item.kind === "short" ? "border-l-2 border-line pl-2.5" : "")}>
          {body}
        </p>
      ) : null}

      <footer className="mt-auto flex items-center gap-1.5 pt-3 text-[11.5px] text-muted">
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
          <span className="flex h-4 w-4 items-center justify-center rounded-full text-[8px] font-medium text-white" style={{ background: p.tint }}>
            {(item.author || p.label).slice(0, 1)}
          </span>
        )}
        <span className="max-w-[52%] truncate">{item.author || p.label}</span>
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

      <Reasons item={item} />
    </article>
  );
}