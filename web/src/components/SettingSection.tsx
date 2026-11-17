import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  id: string;
  title: string;
  /** 收起时露在标题下的一句说明 */
  desc?: string;
  /** 收起时也能看到的关键状态（chip 或一行小字） */
  summary?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * 设置页的一块。默认收起，只露一行摘要——参考了 macOS 系统设置与 Linear 的做法：
 * 一屏能看到全部类目，点开才占地方，避免「所有开关一起摊在面前」。
 */
export default function SettingSection({ id, title, desc, summary, open, onToggle, children }: Props) {
  const reduce = useReducedMotion();
  return (
    <section id={id} className="scroll-mt-24 overflow-hidden rounded-card border border-line bg-white">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-wash/50"
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-[15px] font-semibold tracking-tight">{title}</span>
            {open ? null : <ChevronDown size={13} className="text-fade opacity-0" aria-hidden />}
          </span>
          {desc && !open ? <span className="mt-0.5 block truncate text-[12px] text-fade">{desc}</span> : null}
          {!open && summary ? <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">{summary}</span> : null}
        </span>
        <motion.span
          aria-hidden
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: reduce ? 0 : 0.22, ease: EASE }}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-muted"
        >
          <ChevronDown size={14} />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{
              height: { duration: reduce ? 0 : 0.3, ease: EASE },
              opacity: { duration: reduce ? 0 : 0.16, ease: "easeOut" },
            }}
            style={{ overflow: "hidden" }}
          >
            <div className="px-5 pb-5">{children}</div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
