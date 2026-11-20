import { useEffect } from "react";
import Lenis from "lenis";

/**
 * 侧栏滚动区的滚轮缓动。
 *
 * 上一版是手写的「位置缓动」：每个 wheel 事件把目标位加上 delta，再逐帧指数逼近。
 * 它只缓动位置、不累积速度，所以连滚三格读起来是「嗒、嗒、嗒」三段，
 * 而不是一次带惯性的滑动。这里换成 Lenis：它把滚轮折算成速度并持续积分，
 * 连滚会把行程叠起来，松手后自然衰减。
 *
 * 一个容器一个实例（wrapper 就是滚动容器本身），不劫持 window 的滚轮：
 * 页面本体已经有 useScrollSpeedCap 在按每秒像素上限放行，两边叠在一起会互相抢。
 * 容器用 [data-smooth-scroll] 标记，挂载时机不固定（会话列表、右栏、线程都是后挂的），
 * 所以用 MutationObserver 增量接管、卸载时销毁。
 */

const SELECTOR = "[data-smooth-scroll]";
/** 每帧吃掉剩余距离的比例。0.09 ≈ 300–400ms 稳住，比默认 0.1 略沉一点 */
const LERP = 0.09;
/** Windows 一格滚轮 100px 偏肉，略放大到跟手 */
const WHEEL_MULTIPLIER = 1.15;

const instances = new Map<HTMLElement, Lenis>();
let paused = false;
let observer: MutationObserver | null = null;
let refreshTimer = 0;
let resizeTimer = 0;

/** Mac 触控板自带惯性，再套一层会「滑过头」；reduce 交给 Lenis 自己的 respectReducedMotion */
function shouldSkip(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}

function create(el: HTMLElement): void {
  if (instances.has(el) || !el.isConnected) return;
  const overflowY = window.getComputedStyle(el).overflowY;
  if (!/(auto|scroll)/.test(overflowY)) return;
  const lenis = new Lenis({
    wrapper: el,
    content: el,
    lerp: LERP,
    wheelMultiplier: WHEEL_MULTIPLIER,
    smoothWheel: true,
    syncTouch: false,
    overscroll: false,
    autoRaf: true,
    // 容器里自己滚的块（代码块、图片条）交还给浏览器，别被外层吃掉
    prevent: (node) => node instanceof HTMLElement && Boolean(node.closest("[data-lenis-prevent]")),
  });
  if (paused) lenis.stop();
  instances.set(el, lenis);
}

function scan(root: ParentNode): void {
  if (root instanceof HTMLElement && root.matches(SELECTOR)) create(root);
  root.querySelectorAll(SELECTOR).forEach((node) => {
    if (node instanceof HTMLElement) create(node);
  });
}

function refresh(): void {
  for (const [el, lenis] of instances) {
    if (el.isConnected) continue;
    lenis.destroy();
    instances.delete(el);
  }
  scan(document);
  // 追加行不会改变容器的盒子尺寸，ResizeObserver 收不到，可滚范围得自己重算
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    instances.forEach((lenis) => lenis.resize());
  }, 80);
}

function scheduleRefresh(): void {
  // 流式输出时 DOM 每帧都在变，扫描本身要合并，不能一次 mutation 扫一遍整棵树
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(refresh, 120);
}

function install(): void {
  if (observer) return;
  scan(document);
  observer = new MutationObserver(scheduleRefresh);
  observer.observe(document.body, { childList: true, subtree: true });
}

function destroy(): void {
  observer?.disconnect();
  observer = null;
  window.clearTimeout(refreshTimer);
  window.clearTimeout(resizeTimer);
  instances.forEach((lenis) => lenis.destroy());
  instances.clear();
}

/** 在 App 里挂一次：把带 [data-smooth-scroll] 的滚动容器接管成惯性滚动 */
export function useSmoothWheelScroll(): void {
  useEffect(() => {
    if (shouldSkip()) return;
    install();
    return destroy;
  }, []);
}

/**
 * 模态层打开时暂停：确认框、灯箱盖住整页，底下的侧栏不该还能被滚。
 * Lenis 的 stop() 只是停积分，不动容器样式（autoToggle 才改 overflow）。
 */
export function usePauseSidebarScroll(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    paused = true;
    instances.forEach((lenis) => lenis.stop());
    return () => {
      paused = false;
      instances.forEach((lenis) => lenis.start());
    };
  }, [active]);
}
