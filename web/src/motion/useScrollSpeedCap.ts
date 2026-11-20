import { useEffect } from "react";
import { isPageScrollLocked } from "./useScrollLock";

/**
 * 信息流的速度上限。
 *
 * 刷得太快时，页面能一屏一屏地跳到还没取回来的地方，停下来只剩一片空。
 * 这里接管滚轮：把要滚的距离攒进 pending，每帧只放行 MAX_SPEED × dt 那么多，
 * 剩下的下一帧继续 —— 手感还是「一直在滚」，但不会一瞬间冲出去好几屏。
 *
 * 不接管的：侧栏/抽屉/对话流里自己的滚动容器、Ctrl+滚轮（缩放）、reduced-motion。
 */
const MAX_SPEED = 2400;
/** 一帧最多补这么多秒，切标签页回来时 dt 会很大，别一次放行一大段 */
const MAX_DT = 0.064;

/** 事件目标在不在一个「自己的」滚动容器里：在的话这次滚轮不该由页面消费 */
function ownsScroll(node: EventTarget | null): boolean {
  let el = node instanceof Element ? node : null;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    if (
      (style.overflowY === "auto" || style.overflowY === "scroll") &&
      el.scrollHeight > el.clientHeight + 4
    ) {
      return true;
    }
    el = el.parentElement;
  }
  return false;
}

export function useScrollSpeedCap(enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let pending = 0;
    let raf = 0;
    let last = 0;

    const step = (at: number) => {
      if (!last) last = at;
      const dt = Math.min(MAX_DT, Math.max(0, at - last) / 1000);
      last = at;
      const budget = MAX_SPEED * dt;
      const move = Math.sign(pending) * Math.min(Math.abs(pending), budget);
      pending -= move;
      if (move && !isPageScrollLocked()) window.scrollBy(0, move);
      if (Math.abs(pending) > 1) {
        raf = requestAnimationFrame(step);
      } else {
        raf = 0;
        last = 0;
      }
    };

    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.defaultPrevented) return;
      // 模态层锁着整页时滚轮谁也别吃：这里是自己 scrollBy 实现的缓动，
      // 只给 html 加 overflow:hidden 拦不住它（I-05 的确认框实测 614→1264）。
      if (isPageScrollLocked()) {
        e.preventDefault();
        return;
      }
      if (!e.deltaY || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
      if (ownsScroll(e.target)) return;
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? window.innerHeight : 1;
      e.preventDefault();
      pending += e.deltaY * unit;
      if (!raf) raf = requestAnimationFrame(step);
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      window.removeEventListener("wheel", onWheel);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled]);
}
