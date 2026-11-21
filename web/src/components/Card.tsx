import { memo, useRef, useState, type CSSProperties } from "react";
import { motion } from "framer-motion";
import { prefetchItem } from "../api";
import { loadItemPage } from "../pages/itemPageLoader";
import {
  FileText,
  Heart,
  Image as ImageIcon,
  Link2,
  MessageCircle,
  MoreHorizontal,
  Play,
  Quote,
  Sparkles,
  Star,
} from "lucide-react";
import { useAgentActions } from "../agent/AgentProvider";
import { useIsSaved } from "../agent/savedStore";
import CardMenu, { type CardMenuItem } from "./CardMenu";
import type { FeedItem } from "../api";
import { KIND_LABEL, platform } from "../platform";
import { duration, num, timeAgo } from "../format";

interface Props {
  item: FeedItem;
  /** 一起把被点的卡片元素和自己的数据交出去：转场要给媒体框/标题挂名字，
      详情页也能拿这条数据垫首屏（不必等接口回来才长出共享元素） */
  /** onOpen(id, el, item) */
  onOpen: (id: string, el: HTMLElement, item?: FeedItem) => void;
  /** 从详情页返回时，给目标卡片的媒体框和标题挂上 of-media / of-title，让详情页缩回它的位置 */
  vtNames?: { media?: string | null; title?: string | null };
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
    // 单列时卡片能到 1140 宽，16:9 的封面会吃掉整整一屏；封顶 420 之后溢出裁掉，
    // 视觉上就是一块电影感的宽幅封面，而不是把下面的标题顶出视野
    <div data-media className="relative w-full aspect-video max-h-[420px] overflow-hidden rounded-lg bg-wash">
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
          decoding="async"
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
              decoding="async"
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
        <p className="card-excerpt mt-1.5 flex-1 overflow-hidden pb-3 leading-[1.7] text-ink/75">{text}</p>
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
      <p className={"clamp-2 card-meta mt-1.5 shrink-0 leading-[1.65] text-muted " + (item.kind === "short" ? "border-l-2 border-line pl-2.5" : "")}>
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
    <p className={"clamp-2 card-meta card-meta-quiet mt-1.5 shrink-0 leading-[1.7] " + (hint ? "text-fade" : "")}>
      {hint || "\u00a0"}
    </p>
  );
}

/** memo：信息流一次渲染 30 张卡，父组件因为筛选、进度、轮询重渲染时
    卡片本体不该跟着重算（每张卡里都有一坨时间格式化与平台查表）。 */
function Card({ item, onOpen, vtNames }: Props) {
  const p = platform(item.platform);
  const body = excerpt(item);
  const kindLabel = KIND_LABEL[item.kind] ?? item.kind;
  const hoverTimer = useRef<number | null>(null);
  const linkRef = useRef<HTMLAnchorElement | null>(null);
  // 卡片根节点：菜单里的「查看 AI 总结」要拿它当转场的起点（媒体框/标题都在它里面）
  const cardRef = useRef<HTMLElement | null>(null);
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const { toggleSave } = useAgentActions();
  // 只订阅自己这一条：整屏卡片读 saved 的话，点一颗星会让 30 张卡一起重渲染
  const isSaved = useIsSaved(item.id) || Boolean(item.saved);

  /** 卡片本身是 <a>：里面这些按钮必须先掐掉跳转，否则点收藏会把人送走 */
  const swallow = (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const copyLink = () => {
    const announce = () => window.dispatchEvent(new CustomEvent("onefeed:toast", { detail: { text: "已复制原平台链接" } }));
    if (navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(item.url).then(announce).catch(fallbackCopy);
      return;
    }
    fallbackCopy();
    function fallbackCopy() {
      const area = document.createElement("textarea");
      area.value = item.url;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        announce();
      } finally {
        area.remove();
      }
    }
  };

  const menuItems: CardMenuItem[] = [
    {
      id: "save",
      label: isSaved ? "移出稍后再看" : "稍后再看",
      icon: <Star size={13} fill={isSaved ? "currentColor" : "none"} />,
      onSelect: () => toggleSave(item.id),
    },
    { id: "copy", label: "复制原平台链接", icon: <Link2 size={13} />, onSelect: copyLink },
    {
      id: "summary",
      label: "查看 AI 总结",
      icon: <Sparkles size={13} />,
      onSelect: () => onOpen(item.id, cardRef.current ?? document.body, item),
    },
  ];

  /* 指针停一下就开始预取：转场结束时数据大概率已经就位，不会飞进去撞见骨架屏 */
  const schedulePrefetch = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    // 详情页是独立 chunk：hover 一下就把模块拿下来，换算力给「首屏不需要的东西」
    void loadItemPage();
    // 600ms 才认「停在这张卡上」：260ms 时慢扫一屏就会连拉十几条，网络和主线程都在忙
    hoverTimer.current = window.setTimeout(() => prefetchItem(item.id), 600);
  };
  const cancelPrefetch = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
  };

  return (
    <motion.article
      ref={cardRef}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.985 }}
      transition={{ type: "spring", stiffness: 420, damping: 34, mass: 0.7 }}
      style={{ containerType: "inline-size" } as CSSProperties}
      className="group card-pad relative flex h-full min-h-[14rem] flex-col rounded-card border border-line bg-card text-left transition-colors hover:border-ink/25 hover:shadow-card focus-within:ring-2 focus-within:ring-ink/20"
    >
      {/* 链接铺满整张卡（stretched link）。以前是 <a> 包着内容、里面再放两个按钮，
          浏览器解析出来是 a > button 的非法嵌套：能点，但语义错、读屏会念成两层控件。
          现在根是 article，可点面积、中键/⌘点击、右键「在新标签页打开」全都不变。 */}
      <a
        ref={linkRef}
        href={"/item/" + encodeURIComponent(item.id)}
        aria-label={p.label + " · " + kindLabel + " · " + item.title}
        onClick={(e) => {
          // 只接管「普通左键单击」这一种。中键、⌘/Ctrl+单击、Shift+单击仍旧交给浏览器：
          // 聚合器的核心用法就是一次开一堆标签页，不能因为做了转场就把这条路堵死。
          if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
          e.preventDefault();
          onOpen(item.id, e.currentTarget, item);
        }}
        onPointerEnter={schedulePrefetch}
        onPointerLeave={cancelPrefetch}
        onFocus={schedulePrefetch}
        // 按下的那一刻就开始下模块：等到 click 再下，冷卡要多等一个往返
        onPointerDown={(e) => {
          if (e.button === 0) void loadItemPage();
        }}
        className="absolute inset-0 z-0 rounded-card focus-visible:outline-none"
      />
      {/* 内容层不接指针：点在标题/正文上其实点到的是下面那张铺满的链接。
          两个按钮各自把自己放回可点层（见页脚）。 */}
      <div className="pointer-events-none relative flex h-full flex-col">
      <header className="flex h-5 shrink-0 items-center gap-2 text-[11px]">
        <PlatformBadge item={item} />
        <span className="text-muted">{kindLabel}</span>
        {item.saved ? (
          <span className="flex items-center gap-0.5 text-accent" title="已收藏">
            <Star size={11} fill="currentColor" />
          </span>
        ) : null}
        {item.published_at ? <span className="ml-auto tabular-nums text-fade">{timeAgo(item.published_at)}</span> : null}
      </header>

      {/* 这两块是共享元素的两端：点开时它们从卡片里长大成详情页的媒体区和标题 */}
      <div
        data-vt="media"
        className="mt-2.5 shrink-0"
        style={vtNames?.media ? { viewTransitionName: vtNames.media } : undefined}
      >
        <Media item={item} />
      </div>

      <h3
        data-vt="title"
        className="clamp-2 card-title mt-2.5 shrink-0 font-display font-semibold tracking-tight"
        style={vtNames?.title ? { viewTransitionName: vtNames.title } : undefined}
      >
        {item.title}
      </h3>

      <MetaLine item={item} body={body} />

      <footer className="mt-auto flex items-center gap-1.5 pt-2.5 text-[12px] text-muted">
        {item.author_avatar ? (
          <img
            src={item.author_avatar}
            alt=""
            loading="lazy"
            decoding="async"
            width={16}
            height={16}
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
        {/* 卡片操作：常驻而不是 hover 才出现 —— 触屏没有 hover，键盘用户也不该先猜一下 */}
        <span className="pointer-events-auto ml-1.5 flex shrink-0 items-center gap-0.5 border-l border-line pl-1">
          <button
            onClick={(event) => {
              swallow(event);
              toggleSave(item.id);
            }}
            aria-label={isSaved ? "移出稍后再看" : "稍后再看"}
            aria-pressed={isSaved}
            title={isSaved ? "移出稍后再看" : "稍后再看"}
            className={
              "flex h-6 w-6 items-center justify-center rounded-full transition hover:bg-wash " +
              (isSaved ? "text-accent" : "text-fade hover:text-ink")
            }
          >
            <Star size={13} fill={isSaved ? "currentColor" : "none"} />
          </button>
          <button
            ref={moreRef}
            onClick={(event) => {
              swallow(event);
              setMenuOpen((prev) => !prev);
            }}
            aria-label="更多操作"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title="更多操作"
            className="flex h-6 w-6 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink"
          >
            <MoreHorizontal size={14} />
          </button>
        </span>
      </footer>
      </div>
      {menuOpen && moreRef.current ? (
        <CardMenu anchor={moreRef.current} items={menuItems} onClose={() => setMenuOpen(false)} />
      ) : null}
    </motion.article>
  );
}

export default memo(Card);