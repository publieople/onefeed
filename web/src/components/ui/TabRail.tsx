import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { motion, useReducedMotion } from "framer-motion";
import { useRef } from "react";
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
  value: string;
  onChange: (value: string) => void;
  label: string;
}

/**
 * 一排单选胶囊。选中块是同一个 motion 元素，在两项之间滑过去，
 * 所以切换时看到的是「一个椭圆挪了位置」，而不是两处背景色同时闪一下。
 */
export default function TabRail({ id, items, value, onChange, label }: Props) {
  const reduce = useReducedMotion();
  const rail = useRef<HTMLDivElement>(null);

  const pick = (next: string) => {
    const v = next || "all";
    onChange(v);
    // 选到屏幕外的项时把它带进可视区，不然胶囊像是滑丢了
    requestAnimationFrame(() => {
      rail.current?.querySelector<HTMLElement>('[data-value="' + v + '"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
    });
  };

  return (
    <div className="flex min-w-0 items-center rounded-full border border-line bg-paper p-1">
      <ToggleGroup.Root
        ref={rail}
        type="single"
        value={value}
        onValueChange={pick}
        aria-label={label}
        className="flex min-w-0 items-center gap-0.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item) => {
          const on = item.id === value;
          return (
            <ToggleGroup.Item
              key={item.id}
              value={item.id}
              data-value={item.id}
              className={
                "relative shrink-0 rounded-full px-3 py-1.5 text-[13px] leading-none transition-colors duration-150 " +
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/20 " +
                (on ? "text-solid-fg" : "text-muted hover:bg-wash hover:text-ink")
              }
            >
              {on ? (
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
                  <span className={"text-[11px] tabular-nums " + (on ? "text-solid-fg/60" : "text-fade")}>{item.count}</span>
                )}
              </span>
            </ToggleGroup.Item>
          );
        })}
      </ToggleGroup.Root>
    </div>
  );
}
