import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { SPRING } from "../../motion";

export interface RailItem {
  id: string;
  label: string;
  count?: number;
  tint?: string;
}

interface Props {
  /** layoutId 的后缀，同一页里多个 rail 要各用各的 */
  id: string;
  items: RailItem[];
  /** 选中的平台 id；空数组 = 全部 */
  value: string[];
  onChange: (next: string[]) => void;
  label: string;
}

/**
 * 一排多选胶囊，交互照文件管理器：单击只留这一个，Ctrl 加/减，Shift 选一段。
 * 滑动高亮只跟「最后点的那个」走 —— 一个椭圆在移动，比好几块背景同时亮更好认；
 * 其余被选中的项给一层浅底，所以多选时也看得出选了哪几个。
 */
export default function TabRail({ id, items, value, onChange, label }: Props) {
  const reduce = useReducedMotion();
  const rail = useRef<HTMLDivElement>(null);
  const anchor = useRef<string | null>(null);
  const [primary, setPrimary] = useState<string>("all");

  const key = value.join(",");
  useEffect(() => {
    setPrimary((prev) => (value.length === 0 ? "all" : value.includes(prev) ? prev : value[0]));
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const platforms = items.filter((item) => item.id !== "all").map((item) => item.id);

  const bring = (target: string) => {
    requestAnimationFrame(() => {
      rail.current?.querySelector<HTMLElement>('[data-value="' + target + '"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
    });
  };

  const choose = (target: string, mods: { ctrl: boolean; shift: boolean }) => {
    if (target === "all") {
      anchor.current = null;
      setPrimary("all");
      onChange([]);
      bring("all");
      return;
    }

    let next: string[];
    if (mods.shift && anchor.current && anchor.current !== target) {
      const from = platforms.indexOf(anchor.current);
      const to = platforms.indexOf(target);
      if (from >= 0 && to >= 0) {
        const [lo, hi] = from < to ? [from, to] : [to, from];
        const range = platforms.slice(lo, hi + 1);
        next = mods.ctrl ? Array.from(new Set([...value, ...range])) : range;
      } else {
        next = [target];
      }
    } else if (mods.ctrl) {
      next = value.includes(target) ? value.filter((each) => each !== target) : [...value, target];
      anchor.current = target;
    } else {
      next = value.length === 1 && value[0] === target ? [] : [target];
      anchor.current = target;
    }

    setPrimary(target);
    onChange(next);
    bring(target);
  };

  const step = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const order = ["all", ...platforms];
    const at = Math.max(0, order.indexOf(primary));
    const nextAt = event.key === "ArrowRight" ? Math.min(order.length - 1, at + 1) : Math.max(0, at - 1);
    const target = order[nextAt];
    choose(target, { ctrl: false, shift: false });
    rail.current?.querySelector<HTMLElement>('[data-value="' + target + '"]')?.focus();
  };

  return (
    <div className="w-fit max-w-full rounded-full border border-line bg-paper p-1">
      <div
        ref={rail}
        role="group"
        aria-label={label}
        onKeyDown={step}
        className="flex min-w-0 items-center gap-0.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item) => {
          const on = item.id === "all" ? value.length === 0 : value.includes(item.id);
          const lead = primary === item.id && on;
          return (
            <button
              key={item.id}
              type="button"
              data-value={item.id}
              aria-pressed={on}
              tabIndex={primary === item.id ? 0 : -1}
              onClick={(event) => choose(item.id, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey })}
              className={
                "relative shrink-0 rounded-full px-3 py-1.5 text-[13px] leading-none transition-colors duration-150 " +
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/20 " +
                (lead ? "text-solid-fg" : on ? "bg-wash text-ink" : "text-muted hover:bg-wash hover:text-ink")
              }
            >
              {lead ? (
                <motion.span
                  layoutId={"rail-" + id}
                  className="absolute inset-0 rounded-full bg-solid shadow-sm"
                  transition={reduce ? { duration: 0 } : SPRING}
                />
              ) : null}
              <span className="relative flex items-center gap-1.5">
                {item.tint ? <span className="h-[7px] w-[7px] rounded-full" style={{ background: item.tint }} /> : null}
                {item.label}
                {item.count === undefined ? null : (
                  <span className={"text-[11px] tabular-nums " + (lead ? "text-solid-fg/60" : on ? "text-muted" : "text-fade")}>{item.count}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
