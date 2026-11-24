import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, RotateCw } from "lucide-react";
import type { Health, PlatformHealth } from "../api";
import { platform } from "../platform";
import { useModalScope } from "../motion/useModalScope";

// 插件没装好时后端只能拿 id 兜底，界面上还是叫「B 站」更像人话
const nameOf = (p: PlatformHealth) =>
  p.label && p.label !== p.platform ? p.label : platform(p.platform).label;

/**
 * 采集情况：顶栏右组里的一枚胶囊。
 * 以前这里是「1327 条 · 最近采集 21:00」一行裸文本，宽度随字数跳、和按钮组不在一个节奏上。
 * 现在收成和图标按钮同高的一件，点开才看每个平台各多少条、上次什么时候抓的。
 *
 * 失败、久未更新、插件读不动不能等用户点开才发现：胶囊上常驻一枚警示点，
 * 浮层里逐行说清哪个平台怎么了，能重试的直接就地重试。
 */
export default function CollectPill({
  health,
  onRetry,
}: {
  health: Health | null;
  onRetry: (platforms: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement | null>(null);
  const btn = useRef<HTMLButtonElement | null>(null);

  // 面板开着的时候，全局快捷键（/、?、j/k…）让位给这层
  useModalScope(open);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (t && wrap.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      // 面板一关焦点就落回 body，键盘用户会不知道自己在哪
      btn.current?.focus({ preventScroll: true });
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const count = health?.items ?? 0;
  // 按最近采集排：刚抓过的平台在上面，一眼能看出哪几个是活的；
  // 有问题的平台插到最前面，别让「21:24」把「失败」压到列表底下。
  const rows = [...(health?.platforms ?? [])].sort((a, b) => {
    const rank = (p: PlatformHealth) => (p.state === "failed" || p.state === "unavailable" ? 0 : p.state === "stale" ? 1 : 2);
    const d = rank(a) - rank(b);
    return d !== 0 ? d : b.last_fetched_at - a.last_fetched_at;
  });
  const newest = rows.reduce((max, p) => Math.max(max, p.last_fetched_at), 0);
  const attention = rows.filter((p) => p.state === "failed" || p.state === "stale" || p.state === "unavailable");
  const retryable = attention.filter((p) => p.available && (p.state === "failed" || p.state === "stale"));
  const pluginErrors = health?.plugin_errors ?? [];

  const retry = (ids: string[]) => {
    if (!ids.length) return;
    setOpen(false);
    onRetry(ids);
  };

  return (
    <div ref={wrap} className="relative flex items-center">
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={
          attention.length
            ? attention.length + " 个平台需要看一眼：" + attention.map(nameOf).join("、")
            : count
              ? count + " 条，最近采集 " + clockOf(newest)
              : "还没有内容"
        }
        className={
          "flex hit-44 h-9 items-center gap-1.5 rounded-full pl-2.5 pr-1.5 text-[12px] transition " +
          (open ? "bg-wash text-ink" : attention.length ? "text-ink hover:bg-wash" : "text-muted hover:bg-wash hover:text-ink")
        }
      >
        {/* 一个点回答两件事：库里有没有东西、有没有平台出事。出事先报事。 */}
        <span
          aria-hidden
          className={
            "h-1.5 w-1.5 shrink-0 rounded-full " +
            (attention.length ? "bg-danger" : count ? "bg-accent" : "bg-line")
          }
        />
        <span className="tabular-nums">{count ? count + " 条" : "还没有内容"}</span>
        {attention.length ? (
          <span className="flex items-center gap-0.5 text-danger">
            <AlertTriangle size={11} aria-hidden />
            <span className="tabular-nums">{attention.length}</span>
          </span>
        ) : count ? (
          <span className="hidden text-fade sm:inline">· {clockOf(newest)}</span>
        ) : null}
        <ChevronDown
          size={12}
          className={"shrink-0 text-fade transition-transform duration-200 " + (open ? "rotate-180" : "")}
        />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="采集情况"
          className="absolute right-0 top-full z-40 mt-2 w-[296px] rounded-[10px] border border-line bg-paper p-3 shadow-pop"
        >
          <div className="flex items-baseline justify-between">
            <span className="text-[12px] text-muted">采集情况</span>
            <span className="text-[12px] tabular-nums text-ink">{count} 条</span>
          </div>

          {attention.length ? (
            <p className="mt-1.5 text-[11px] leading-relaxed text-danger">
              {attention.length} 个平台需要处理，抓不到新内容时先从这儿看。
            </p>
          ) : null}

          <div className="mt-2">
            {rows.length ? (
              rows.map((p) => {
                const tone = stateTone(p);
                return (
                  <div key={p.platform} className="group flex items-center gap-2 py-1 text-[12px]">
                    <span
                      aria-hidden
                      className={"h-1.5 w-1.5 shrink-0 rounded-full " + tone.dotClass}
                      style={tone.dotClass ? undefined : { background: platform(p.platform).tint }}
                    />
                    <span className="min-w-0 flex-1 truncate text-muted" title={p.error || p.note || nameOf(p)}>
                      {nameOf(p)}
                    </span>
                    {tone.tag ? (
                      <span className={"shrink-0 text-[10.5px] " + tone.className}>{tone.tag}</span>
                    ) : null}
                    <span className="shrink-0 tabular-nums text-ink">{p.count}</span>
                    <span className="w-10 shrink-0 text-right tabular-nums text-fade">
                      {p.last_fetched_at ? clockOf(p.last_fetched_at) : "—"}
                    </span>
                    {p.available && (p.state === "failed" || p.state === "stale") ? (
                      <button
                        type="button"
                        onClick={() => retry([p.platform])}
                        title={"重试 " + nameOf(p)}
                        aria-label={"重试 " + nameOf(p)}
                        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-fade opacity-0 transition hover:bg-wash hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        <RotateCw size={11} />
                      </button>
                    ) : null}
                  </div>
                );
              })
            ) : (
              <p className="py-1 text-[12px] text-fade">还没抓到任何内容。</p>
            )}
          </div>

          {pluginErrors.length ? (
            <p className="mt-2 border-t border-line pt-2 text-[11px] leading-relaxed text-danger">
              {pluginErrors[0]}
              {pluginErrors.length > 1 ? "，还有 " + (pluginErrors.length - 1) + " 个插件也读不动" : ""}
            </p>
          ) : null}

          <div className="mt-2 flex items-center justify-between gap-2 border-t border-line pt-2 text-[11px] text-fade">
            <span className="truncate">
              最近采集 <span className="tabular-nums">{newest ? agoOf(newest) : "—"}</span>
            </span>
            {retryable.length ? (
              <button
                type="button"
                onClick={() => retry(retryable.map((p) => p.platform))}
                className="flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-muted transition hover:bg-wash hover:text-ink"
              >
                <RotateCw size={10} />
                重试 {retryable.length} 个
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 每个状态一套点色 + 小标签；ok 的没有标签，不拿装饰抢注意力 */
function stateTone(p: PlatformHealth): { dotClass: string; tag: string; className: string } {
  if (!p.available) return { dotClass: "bg-fade", tag: "插件读不动", className: "text-danger" };
  if (p.state === "failed") return { dotClass: "bg-danger", tag: "失败", className: "text-danger" };
  if (p.state === "stale") return { dotClass: "bg-danger/60", tag: "久未更新", className: "text-danger/80" };
  if (p.interrupted) return { dotClass: "bg-danger/60", tag: "没跑完", className: "text-danger/80" };
  if (p.running) return { dotClass: "bg-accent", tag: "正在抓", className: "text-accent" };
  return { dotClass: "", tag: "", className: "" };
}

function clockOf(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

function agoOf(ts: number): string {
  const min = Math.floor((Date.now() / 1000 - ts) / 60);
  if (min < 1) return "刚刚";
  if (min < 60) return min + " 分钟前";
  const hour = Math.floor(min / 60);
  if (hour < 24) return hour + " 小时前";
  return Math.floor(hour / 24) + " 天前";
}
