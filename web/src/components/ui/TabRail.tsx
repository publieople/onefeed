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

type Segment =
  | { kind: "run"; items: RailItem[]; origin: "left" | "right" | "center" }
  | { kind: "item"; item: RailItem };

/**
 * 一排多选胶囊，交互照文件管理器：单击只留这一个，Ctrl 加/减，Shift 选一段。
 *
 * 选中态按「连续段」画：挨着的选中项合并成一整条黑胶囊，中间断开就分成两条。
 * 合并时靠共享 layoutId 让胶囊原地伸长（前一段的起点不变，动画自然连过去）；
 * 断点处长出的新胶囊从相邻那段的方向扩散出来，而不是凭空出现。
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

  const isOn = (item: RailItem) => (item.id === "all" ? value.length === 0 : value.includes(item.id));

  const segments: Segment[] = [];
  for (const item of items) {
    if (!isOn(item)) {
      segments.push({ kind: "item", item });
      continue;
    }
    const last = segments[segments.length - 1];
    if (last && last.kind === "run") {
      last.items.push(item);
    } else {
      segments.push({ kind: "run", items: [item], origin: "center" });
    }
  }
  // 新长出来的胶囊朝「已经有选中段的那一侧」扩散，读起来像从前一段延伸出去
  segments.forEach((seg, index) => {
    if (seg.kind !== "run") return;
    const before = segments.slice(0, index).some((each) => each.kind === "run");
    const after = segments.slice(index + 1).some((each) => each.kind === "run");
    seg.origin = before ? "left" : after ? "right" : "center";
  });

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

  const chip = (item: RailItem, inside: boolean) => (
    <button
      key={item.id}
      type="button"
      data-value={item.id}
      aria-pressed={isOn(item)}
      tabIndex={primary === item.id ? 0 : -1}
      onClick={(event) => choose(item.id, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey })}
      className={
        "relative shrink-0 rounded-full px-3 py-1.5 text-[13px] leading-none transition-colors duration-150 " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/20 " +
        (inside ? "text-solid-fg" : "text-muted hover:bg-wash hover:text-ink")
      }
    >
      <span className="relative flex items-center gap-1.5">
        {item.tint ? <span className="h-[7px] w-[7px] rounded-full" style={{ background: item.tint }} /> : null}
        {item.label}
        {item.count === undefined ? null : (
          <span className={"text-[11px] tabular-nums " + (inside ? "text-solid-fg/60" : "text-fade")}>{item.count}</span>
        )}
      </span>
    </button>
  );

  return (
    <div className="w-fit max-w-full rounded-full border border-line bg-paper p-1">
      <div
        ref={rail}
        role="group"
        aria-label={label}
        onKeyDown={step}
        className="flex min-w-0 items-center gap-0.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {segments.map((seg) => {
          if (seg.kind === "item") return chip(seg.item, false);
          const lead = seg.items[0];
          return (
            <motion.div
              key={"run-" + lead.id}
              layoutId={"rail-" + id + "-" + lead.id}
              initial={reduce ? false : { opacity: 0, scale: 0.86 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={reduce ? { duration: 0 } : SPRING}
              style={{ transformOrigin: seg.origin }}
              className="relative flex shrink-0 items-center overflow-hidden rounded-full bg-solid shadow-sm"
            >
              {seg.items.map((item) => chip(item, true))}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
