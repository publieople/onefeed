import { flushSync } from "react-dom";

type Doc = Document & {
  startViewTransition?: (callback: () => void) => { finished: Promise<void> };
};

/** 卡片与详情页根部共用这个名字，浏览器才能把它们当成同一个元素做变形 */
const CARD_NAME = "of-card";

/**
 * 跳页时套一层 View Transition：被点的卡片长大铺满整页，返回时缩回原位。
 * 浏览器不支持、或用户开了「减少动态效果」时直接跳，不留下任何痕迹。
 */
export function runNavTransition(apply: () => void, target?: HTMLElement | null, back = false): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Doc;
  if (reduce || typeof doc.startViewTransition !== "function") {
    apply();
    return;
  }

  const root = document.documentElement;
  const named = target ?? null;

  let ran = false;
  const run = () => {
    if (ran) return;
    ran = true;
    // React 默认批处理更新，快照可能拿到旧 DOM；这里强制同帧提交
    flushSync(apply);
  };
  const cleanup = () => {
    root.classList.remove("nav-vt");
    root.classList.remove("nav-vt-back");
    if (named) named.style.viewTransitionName = "";
  };

  if (named) named.style.viewTransitionName = CARD_NAME;
  root.classList.add("nav-vt");
  root.classList.toggle("nav-vt-back", back);

  try {
    const vt = doc.startViewTransition(run);
    vt.finished.finally(cleanup).catch(() => {
      /* 过渡被打断不算错，清理已在 finally 里做过 */
    });
  } catch {
    run();
    cleanup();
  }
}
