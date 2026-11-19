import { useCallback, useEffect, useRef } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useHotkeys } from "../motion/useHotkeys";
import { EASE, DUR } from "../motion/tokens";

interface Props {
  open: boolean;
  onClose: () => void;
}

const GROUPS: { title: string; rows: [string, string][] }[] = [
  {
    title: "全局",
    rows: [
      ["/", "打开 AI 输入框"],
    ["⌘ / Ctrl + Shift + K", "同「/」（Ctrl+K 被浏览器占了）"],
      ["Esc", "关闭当前弹层 / 面板"],
      ["?", "这份快捷键表"],
      ["t", "切换亮暗主题"],
      ["r", "刷新一轮采集"],
    ],
  },
  {
    title: "信息流",
    rows: [
      ["j / k", "下一张 / 上一张卡片"],
      ["h / l", "左一列 / 右一列"],
      ["Enter", "打开当前卡片"],
      ["o", "在新标签页打开"],
    ],
  },
  {
    title: "平台胶囊",
    rows: [
      ["← / →", "只挪焦点，不换筛选"],
      ["Home / End", "第一个 / 最后一个"],
      ["Enter / Space", "应用焦点所在的平台"],
      ["⌘ / Ctrl + 点击", "多选"],
      ["Shift + 点击", "连选一段"],
    ],
  },
];

/** 快捷键帮助层：唯一的「我能按什么」出口 */
export default function ShortcutHelp({ open, onClose }: Props) {
  const reduce = useReducedMotion();
  const boxRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => onClose(), [onClose]);
  useHotkeys("dialog", { escape: close }, open);

  useEffect(() => {
    if (!open) return;
    const first = boxRef.current?.querySelector<HTMLElement>("button");
    first?.focus();
  }, [open]);

  // 不用 AnimatePresence：动画帧被节流时（隐藏标签页 / reduce）退出动画收不了尾，
  // 弹层会卡在 DOM 里挡住后面的点击。关闭即时，入场保留。
  if (!open) return null;

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-solid/25 px-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduce ? 0 : DUR.micro }}
      onClick={close}
    >
          <motion.div
            ref={boxRef}
            role="dialog"
            aria-modal="true"
            aria-label="键盘快捷键"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, y: 10, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: reduce ? 0 : DUR.base, ease: EASE }}
            className="w-full max-w-[560px] rounded-card border border-line bg-paper p-5 shadow-pop"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">键盘快捷键</h2>
              <button
                onClick={close}
                className="rounded px-2 py-1 text-[12px] text-fade transition hover:bg-wash hover:text-ink"
              >
                关闭（Esc）
              </button>
            </div>
            <div className="space-y-4">
              {GROUPS.map((group) => (
                <div key={group.title}>
                  <div className="mb-1.5 text-[12px] text-fade">{group.title}</div>
                  <div className="divide-y divide-line/70">
                    {group.rows.map(([keys, what]) => (
                      <div key={keys} className="flex items-center justify-between py-1.5 text-[13px]">
                        <span className="text-muted">{what}</span>
                        <kbd className="rounded border border-line bg-wash px-2 py-0.5 font-mono text-[11px] text-ink">
                          {keys}
                        </kbd>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
    </motion.div>
  );
}
