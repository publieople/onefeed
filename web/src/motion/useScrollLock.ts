import { useEffect } from "react";

/**
 * 模态层锁背景滚动。
 *
 * 之前灯箱和收藏对话框都只写了 `document.body.style.overflow`，
 * 但页面滚动的实际承载者是 html —— body 锁了，html 还能滚，
 * 实测确认框开着时 pageYOffset 照样 0→175。
 *
 * 这里锁 documentElement，并用 scrollbar-gutter: stable 顶住滚动条消失带来的横向位移。
 * 计数式：两层模态嵌套时，先关的那个不能把后关的锁解掉。
 */

let depth = 0;
let saved: { overflow: string; gutter: string } | null = null;

function acquire(): void {
  if (typeof document === "undefined") return;
  depth += 1;
  if (depth > 1) return;
  const html = document.documentElement;
  saved = { overflow: html.style.overflow, gutter: html.style.scrollbarGutter };
  html.style.overflow = "hidden";
  html.style.scrollbarGutter = "stable";
}

function release(): void {
  depth = Math.max(0, depth - 1);
  if (depth > 0 || !saved) return;
  const html = document.documentElement;
  html.style.overflow = saved.overflow;
  html.style.scrollbarGutter = saved.gutter;
  saved = null;
}

/** 现在有没有模态层锁着整页（速度上限要用它让路） */
export function isPageScrollLocked(): boolean {
  return depth > 0;
}

/** active 为真时锁住整页滚动（含 html），卸载或转 false 时还原 */
export function useScrollLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    acquire();
    return release;
  }, [active]);
}
