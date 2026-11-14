import type { CSSProperties } from "react";
import { Heart, MessageCircle, Play } from "lucide-react";
import type { FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface Props {
  item: FeedItem;
  onOpen: (id: string) => void;
}

function ph(tint: string, fade = 0.72): CSSProperties {
  const grad = "linear-gradient(135deg, " + tint + " 0%, " + hexAlpha(tint, fade) + " 60%, " + hexAlpha(tint, 0.28) + " 100%)";
  return { ["--ph" as never]: grad } as CSSProperties;
}

function hexAlpha(hex: string, alpha: number): string {
  const value = Math.round(alpha * 255).toString(16).padStart(2, "0");
  return hex + value;
}

function Cover({ item, ratio }: { item: FeedItem; ratio: string }) {
  return (
    <div className={"thumb w-full " + ratio} style={ph(platform(item.platform).tint)}>
      {item.cover ? (
        <img
          src={item.cover}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[11px] tracking-wide text-white/70">
          {platform(item.platform).label}
        </div>
      )}
      {item.kind === "video" ? (
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/35 backdrop-blur-sm">
            <Play size={15} className="ml-0.5 fill-white text-white" />
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

function Meta({ item }: { item: FeedItem }) {
  const p = platform(item.platform);
  return (
    <div className="mt-2.5 flex items-center gap-1.5 text-[12px] text-muted">
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
        <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: p.tint }} />
      )}
      <span className="max-w-[46%] truncate">{item.author || p.label}</span>
      <span className="text-fade">·</span>
      <span className="text-fade">{timeAgo(item.published_at)}</span>
      {item.like_count > 0 ? (
        <span className="ml-auto flex items-center gap-1 text-fade">
          <Heart size={11} />
          {num(item.like_count)}
        </span>
      ) : item.comment_count > 0 ? (
        <span className="ml-auto flex items-center gap-1 text-fade">
          <MessageCircle size={11} />
          {num(item.comment_count)}
        </span>
      ) : null}
    </div>
  );
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
        <span className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">
          {item.cluster_size} 个平台同题
        </span>
      ) : null}
    </div>
  );
}

function Images({ item }: { item: FeedItem }) {
  const pics = item.images.slice(0, 4);
  const cols = pics.length === 1 ? "grid-cols-1" : pics.length === 2 ? "grid-cols-2" : "grid-cols-3";
  return (
    <div className={"grid gap-1 " + cols}>
      {pics.map((src, i) => (
        <div
          key={src + i}
          className={"thumb w-full " + (pics.length === 1 ? "aspect-[4/3]" : "aspect-square")}
          style={ph(platform(item.platform).tint, 0.82 - i * 0.12)}
        >
          <img
            src={src}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
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
  );
}

export default function Card({ item, onOpen }: Props) {
  const open = () => onOpen(item.id);

  if (item.kind === "video") {
    return (
      <article onClick={open} className="group cursor-pointer">
        <Cover item={item} ratio="aspect-video rounded-card" />
        <h3 className="clamp-2 mt-3 text-[17px] font-semibold leading-[1.35] tracking-tight">{item.title}</h3>
        <Meta item={item} />
        <Reasons item={item} />
      </article>
    );
  }

  if (item.kind === "images") {
    return (
      <article onClick={open} className="group cursor-pointer">
        <Images item={item} />
        <h3 className="clamp-2 mt-3 text-[16px] font-semibold leading-[1.4] tracking-tight">{item.title}</h3>
        <Meta item={item} />
        <Reasons item={item} />
      </article>
    );
  }

  if (item.kind === "list") {
    const rank = Number((item.extra?.rank as number) ?? 0);
    return (
      <article onClick={open} className="group cursor-pointer rounded-card border border-line p-4 transition hover:border-ink/20">
        <div className="flex items-baseline gap-3">
          <span className="w-6 shrink-0 text-[13px] tabular-nums text-fade">
            {rank ? String(rank).padStart(2, "0") : "·"}
          </span>
          <h3 className="clamp-2 text-[15px] font-medium leading-[1.45]">{item.title}</h3>
        </div>
        <div className="mt-2 flex items-center gap-1.5 pl-9 text-[12px] text-fade">
          <span className="h-[6px] w-[6px] rounded-full" style={{ background: platform(item.platform).tint }} />
          {platform(item.platform).label}
          <span>·</span>
          {KIND_LABEL[item.kind] ?? item.kind}
          {item.text ? <span className="ml-auto text-muted">{item.text}</span> : null}
        </div>
      </article>
    );
  }

  if (item.kind === "short") {
    return (
      <article onClick={open} className="group cursor-pointer rounded-card border border-line p-4 transition hover:border-ink/20">
        <h3 className="clamp-2 text-[15px] font-semibold leading-[1.5]">{item.title}</h3>
        {item.text ? (
          <p className="clamp-3 mt-2 border-l-2 border-line pl-3 text-[13px] leading-[1.7] text-muted">{item.text}</p>
        ) : null}
        <div className="mt-2.5 flex items-center gap-1.5 text-[12px] text-fade">
          <span className="h-[6px] w-[6px] rounded-full" style={{ background: platform(item.platform).tint }} />
          {platform(item.platform).label}
          {item.author ? <span className="truncate">· {item.author}</span> : null}
          <span className="ml-auto">{timeAgo(item.published_at)}</span>
        </div>
        <Reasons item={item} />
      </article>
    );
  }

  return (
    <article onClick={open} className="group flex cursor-pointer gap-4 rounded-card border border-line p-4 transition hover:border-ink/20">
      <div className="min-w-0 flex-1">
        <h3 className="clamp-2 text-[16px] font-semibold leading-[1.4] tracking-tight">{item.title}</h3>
        {item.text ? <p className="clamp-2 mt-1.5 text-[13px] leading-[1.6] text-muted">{item.text}</p> : null}
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-fade">
          <span className="h-[6px] w-[6px] rounded-full" style={{ background: platform(item.platform).tint }} />
          {platform(item.platform).label}
          {item.author ? <span className="max-w-[40%] truncate">· {item.author}</span> : null}
          <span className="ml-auto">{timeAgo(item.published_at)}</span>
        </div>
        <Reasons item={item} />
      </div>
      {item.cover ? (
        <div className="thumb h-[86px] w-[118px] shrink-0 rounded-lg" style={ph(platform(item.platform).tint)}>
          <img
            src={item.cover}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      ) : null}
    </article>
  );
}
