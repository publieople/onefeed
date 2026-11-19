/**
 * 全站动效的唯一真源。
 *
 * 之前时长散在各处（0.16 / 0.18 / 0.22 / 0.24 / 0.34 / 0.42 混用），
 * 同一个「面板展开」在三个页面是三个速度，看起来像三个人写的。
 * 现在 JS 从这里取，CSS 侧对应 --dur-* / --ease-out 变量，改一处就是改全站。
 */

/** 主曲线：快起慢收，收得干净 */
export const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** 同上，给 CSS 用 */
export const EASE_CSS = "cubic-bezier(0.22, 1, 0.36, 1)";

/** 秒。命名按「用在哪」分，不按数值分。 */
export const DUR = {
  /** 按下、hover、图标切换这类即时反馈 */
  micro: 0.14,
  /** 图标、小元素切换 */
  fast: 0.16,
  /** 面板、浮层进出 */
  base: 0.24,
  /** 切页 */
  page: 0.26,
  /** 列表逐项进场 */
  list: 0.34,
} as const;

/** DUR 的短别名，新代码用这个 */
export const D = { fast: 0.16, base: 0.24, slow: 0.38, page: 0.42 } as const;

export const SPRING = { type: "spring" as const, stiffness: 420, damping: 34, mass: 0.7 };

/** 面板、抽屉：起手轻，收尾不弹 */
export const SPRING_SOFT = { type: "spring" as const, stiffness: 320, damping: 34 };

/** 胶囊、分段控件这类小控件：跟手、回位快 */
export const SPRING_SNAPPY = { type: "spring" as const, stiffness: 460, damping: 38 };

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
