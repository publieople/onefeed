/** 全站动效只认这几个数，改一处就是改全站。 */
export const EASE = [0.22, 1, 0.36, 1] as const;

export const DUR = {
  /** 按下、hover 这类即时反馈 */
  micro: 0.14,
  /** 面板、浮层进出 */
  base: 0.24,
  /** 切页 */
  page: 0.26,
  /** 列表逐项进场 */
  list: 0.34,
} as const;

export const SPRING = { type: "spring" as const, stiffness: 420, damping: 34, mass: 0.7 };

/** 列表进场：卡片按顺序错开一点点 */
export const listItem = (index: number) => ({
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: DUR.list, ease: EASE, delay: Math.min(index, 11) * 0.022 },
});

/** 切页：进来的一页从行进方向偏一点再归位，退出的反向淡出。 */
export const pageVariants = (dir: 1 | -1) => ({
  initial: { opacity: 0, y: 14 * dir, scale: 0.995 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -10 * dir, scale: 0.995 },
});
