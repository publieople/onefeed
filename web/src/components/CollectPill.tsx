import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Health } from "../api";
import { platform } from "../platform";
import { useModalScope } from "../motion/useModalScope";

/**
 * 采集情况：顶栏右组里的一枚胶囊。
 * 以前这里是「1327 条 · 最近采集 21:00」一行裸文本，宽度随字数跳、和按钮组不在一个节奏上。
 * 现在收成和图标按钮同高的一件，点开才看每个平台各多少条、上次什么时候抓的。
 */
export default function CollectPill({ health }: { health: Health | null }) {
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
  // 按最近采集排：刚抓过的平台在上面，一眼能看出哪几个是活的
  const rows = [...(health?.platforms ?? [])].sort((a, b) => b.last_fetched_at - a.last_fetched_at);
  const newest = rows.length ? rows[0].last_fetched_at : 0;

  return (
    <div ref={wrap} className="relative flex items-center">
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={count ? count + " 条，最近采集 " + clockOf(newest) : "还没有内容"}
        className={
          "flex hit-44 h-9 items-center gap-1.5 rounded-full pl-2.5 pr-1.5 text-[12px] transition " +
          (open ? "bg-wash text-ink" : "text-muted hover:bg-wash hover:text-ink")
        }
      >
        {/* 有数据亮一点：这枚胶囊首先回答「库里有没有东西」，其次才是数字 */}
        <span aria-hidden className={"h-1.5 w-1.5 shrink-0 rounded-full " + (count ? "bg-accent" : "bg-line")} />
        <span className="tabular-nums">{count ? count + " 条" : "还没有内容"}</span>
        {count ? <span className="hidden text-fade sm:inline">· {clockOf(newest)}</span> : null}
        <ChevronDown
          size={12}
          className={"shrink-0 text-fade transition-transform duration-200 " + (open ? "rotate-180" : "")}
        />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="采集情况"
          className="absolute right-0 top-full z-40 mt-2 w-[272px] rounded-[10px] border border-line bg-paper p-3 shadow-pop"
        >
          <div className="flex items-baseline justify-between">
            <span className="text-[12px] text-muted">采集情况</span>
            <span className="text-[12px] tabular-nums text-ink">{count} 条</span>
          </div>
          <div className="mt-2">
            {rows.length ? (
              rows.map((p) => (
                <div key={p.platform} className="flex items-center gap-2 py-1 text-[12px]">
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ background: platform(p.platform).tint }}
                  />
                  <span className="min-w-0 flex-1 truncate text-muted">{platform(p.platform).label}</span>
                  <span className="shrink-0 tabular-nums text-ink">{p.count}</span>
                  <span className="w-10 shrink-0 text-right tabular-nums text-fade">
                    {p.last_fetched_at ? clockOf(p.last_fetched_at) : "—"}
                  </span>
                </div>
              ))
            ) : (
              <p className="py-1 text-[12px] text-fade">还没抓到任何内容。</p>
            )}
          </div>
          <div className="mt-2 flex items-baseline justify-between border-t border-line pt-2 text-[11px] text-fade">
            <span>最近采集</span>
            <span className="tabular-nums">{newest ? agoOf(newest) : "—"}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
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
