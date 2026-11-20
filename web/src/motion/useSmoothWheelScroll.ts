import { useEffect } from "react";

/**
 * 侧栏滚动区的滚轮缓动。
 *
 * Windows 上的 Chrome 滚轮是一格一格「瞬移」的：一次 wheel 事件直接跳 100~400px，
 * 中间没有帧 —— CSS 的 scroll-behavior 只管键盘和程序化滚动，管不到滚轮。
 * 这里接管带 data-smooth-scroll 的容器：把目标位置攒起来，每帧按指数缓动追过去，
 * 手感接近 macOS 的顺滑，同时不会把页面滚动的限速逻辑顶掉。
 *
 * 不接管的：Ctrl/⌘+滚轮（缩放）、横向滚动、已滚到边（留给 overscroll-behavior 处理）、
 * prefers-reduced-motion。
 */
const TAU_MS = 55;
const MIN_STEP = 0.4;

export function installSmoothWheelScroll(): () => void {
  if (typeof window === "undefined") return () => {};
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => {};
  // macOS 的滚轮本来就带惯性动画，再叠一层缓动会变迟钝；只补 Windows / Linux 的阶梯滚轮
  if (/Mac|iPhone|iPad/.test(navigator.userAgent)) return () => {};

  let node: HTMLElement | null = null;
  let target = 0;
  let raf = 0;
  let last = 0;

  const animate = (now: number) => {
    if (!node) {
      raf = 0;
      return;
    }
    const dt = Math.min(64, Math.max(8, last ? now - last : 16));
    last = now;
    const diff = target - node.scrollTop;
    if (Math.abs(diff) < MIN_STEP) {
      node.scrollTo({ top: target, behavior: "instant" as ScrollBehavior });
      raf = 0;
      return;
    }
    // 必须写 behavior:"instant"：容器上有 scroll-behavior: smooth 时，
    // 直接赋 scrollTop 会被浏览器当成一次平滑滚动，每帧只挪一点点，
    // 缓动就变成了「和浏览器抢方向盘」。
    node.scrollTo({ top: node.scrollTop + diff * (1 - Math.exp(-dt / TAU_MS)), behavior: "instant" as ScrollBehavior });
    raf = requestAnimationFrame(animate);
  };

  /** 找最近的、真的能滚的带标记容器 */
  const container = (from: EventTarget | null): HTMLElement | null => {
    const start = from instanceof Element ? from : null;
    const found = start?.closest<HTMLElement>("[data-smooth-scroll]");
    if (!found) return null;
    const style = getComputedStyle(found);
    if (style.overflowY !== "auto" && style.overflowY !== "scroll") return null;
    if (found.scrollHeight <= found.clientHeight + 1) return null;
    return found;
  };

  const onWheel = (event: WheelEvent) => {
    if (event.ctrlKey || event.metaKey || event.defaultPrevented) return;
    if (!event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    const box = container(event.target);
    if (!box) return;

    const max = box.scrollHeight - box.clientHeight;
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? box.clientHeight : 1;
    const delta = event.deltaY * unit;
    // 到边了就交回去：外层页面还能接住这次滚轮
    if (box.scrollTop <= 0 && delta < 0) return;
    if (box.scrollTop >= max - 1 && delta > 0) return;

    event.preventDefault();
    if (node !== box) {
      node = box;
      raf = 0;
    }
    if (!raf) {
      target = box.scrollTop; // 用户可能刚拖过滚动条，重新对齐
    }
    target = Math.max(0, Math.min(max, target + delta));
    if (!raf) {
      last = 0;
      raf = requestAnimationFrame(animate);
    }
  };

  document.addEventListener("wheel", onWheel, { passive: false, capture: true });
  return () => {
    document.removeEventListener("wheel", onWheel, { capture: true });
    if (raf) cancelAnimationFrame(raf);
  };
}

/** 组件里挂一行即可：进页面装好，卸载时拆掉 */
export function useSmoothWheelScroll(): void {
  useEffect(() => installSmoothWheelScroll(), []);
}
