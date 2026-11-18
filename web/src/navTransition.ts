import { flushSync } from "react-dom";

type Doc = Document & {
  startViewTransition?: (callback: () => void) => { finished: Promise<void> };
};

/** 卡片自己那一层：旧卡片放大淡出，新页面随后淡入 */
const CARD_NAME = "of-card";
/** 从详情回列表：整页缩一点退场，列表反向长回来 */
const PAGE_NAME = "of-page";

/**
 * 跳页时套一层 View Transition，让被点的卡片先轻轻放大再散开。
 * 浏览器不支持、或用户开了「减少动态效果」时直接跳，不留下任何痕迹。
 */
export function runNavTransition(
  apply: () => void,
  target?: HTMLElement | "page" | null,
  back = false,
): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Doc;
  if (reduce || typeof doc.startViewTransition !== "function") {
    apply();
    return;
  }

  const root = document.documentElement;
  const named =
    target === "page" ? (document.querySelector(".page-shell") as HTMLElement | null) : (target ?? null);
  const name = target === "page" ? PAGE_NAME : CARD_NAME;

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

  if (named) named.style.viewTransitionName = name;
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
