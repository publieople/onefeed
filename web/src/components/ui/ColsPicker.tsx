import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Check, Columns3 } from "lucide-react";
import { DUR, EASE } from "../../motion/tokens";
import { popScope, pushScope, useHotkeys } from "../../motion/useHotkeys";
import type { ColsChoice } from "../../layout/useGridCols";

const OPTIONS: { value: ColsChoice; label: string }[] = [
  { value: "auto", label: "自动" },
  { value: 1, label: "1 列" },
  { value: 2, label: "2 列" },
  { value: 3, label: "3 列" },
  { value: 4, label: "4 列" },
  { value: 5, label: "5 列" },
];

interface Props {
  choice: ColsChoice;
  cols: number;
  maxFit: number;
  onChange: (choice: ColsChoice) => void;
}

/**
 * 每行卡片数。选择本身不弹确认、不占 URL：点一下就落到 localStorage，
 * 弹层关掉，网格按新列数重排（重排动画由信息流的 FLIP 负责）。
 *
 * 宽度不够的档位照样能选——图的是换到宽屏 / 收起侧栏后立刻生效，
 * 但当前渲染会被 maxFit 收住，所以选项右边直接标出「最多 N 列」，不让人猜。
 */
export default function ColsPicker({ choice, cols, maxFit, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    pushScope("dialog");
    const onDown = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      popScope("dialog");
    };
  }, [open]);

  useHotkeys("dialog", { escape: () => setOpen(false) }, open);

  const label = choice === "auto" ? "自动 · " + cols + " 列" : cols + " 列";
  const clamped = typeof choice === "number" && choice > maxFit;

  return (
    <div ref={wrap} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        title="每行显示几张卡片（Alt + 0~5）"
        className={`flex items-center gap-1 rounded-full border px-3 py-1 text-[12px] transition ${
          open ? "border-ink/30 text-ink" : "border-line text-muted hover:border-ink/25 hover:text-ink"
        }`}
      >
        <Columns3 size={12} />
        {label}
      </button>

      {open ? (
        <motion.div
          initial={{ opacity: 0, y: -6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: DUR.micro, ease: EASE }}
          role="group"
          aria-label="每行卡片数"
          className="absolute right-0 top-full z-20 mt-2 w-[232px] rounded-card border border-line bg-paper p-1.5 shadow-pop"
        >
          {OPTIONS.map((opt) => {
            const on = opt.value === choice;
            const tight = typeof opt.value === "number" && opt.value > maxFit;
            return (
              <button
                key={String(opt.value)}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition ${
                  on ? "bg-wash text-ink" : "text-muted hover:bg-wash/60 hover:text-ink"
                }`}
              >
                <span className="w-3.5 shrink-0">
                  {on ? <Check size={13} /> : null}
                </span>
                <span className="flex-1">{opt.label}</span>
                {tight ? <span className="text-[11px] text-fade">最多 {maxFit} 列</span> : null}
                {opt.value === "auto" ? <span className="text-[11px] text-fade">按宽度</span> : null}
              </button>
            );
          })}
          {clamped ? (
            <p className="px-2.5 pb-1 pt-1.5 text-[11px] leading-snug text-fade">
              当前宽度最多 {maxFit} 列，选的大档位会先记着，窗口变宽再展开。
            </p>
          ) : null}
        </motion.div>
      ) : null}
    </div>
  );
}
