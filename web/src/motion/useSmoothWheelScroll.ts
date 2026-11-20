import { useEffect } from "react";
import Lenis from "lenis";

/**
 * 侧栏滚动区的滚轮缓动（Lenis）。
 *
 * 三个关键取舍：
 * 1. 单一 rAF：Lenis 自己开 autoRaf 是「一个实例一条常驻 rAF」，首页两条、详情页三条，
 *    空闲时也是 150 次/秒的回调。这里全部实例共用一条循环，且连续 6 帧没有实例在滚就停掉，
 *    下一次滚轮/程序化滚动再 kick 起来。
 * 2. 增量扫描：MutationObserver 给的是 addedNodes，不必每次全文档 querySelectorAll，
 *    流式输出时也不会每 120ms 把所有实例 resize 一遍。
 * 3. 边界放行：Lenis 在容器到底/到顶时仍然 preventDefault，滚轮会被侧栏吃掉。
 *    这里在捕获阶段判断边界，给这一格的 target 临时打 data-lenis-prevent（Lenis 的
 *    composedPath 只看到 wrapper 内部，所以必须打在 target 上），让浏览器把它交给页面滚。
 *
 * 一个容器一个实例（wrapper 就是滚动容器本身），不劫持 window 的滚轮：
 * 页面本体已经有 useScrollSpeedCap 在按每秒像素上限放行，两边叠在一起会互相抢。
 */

const SELECTOR = "[data-smooth-scroll]";
/** 每帧吃掉剩余距离的比例。0.09 ≈ 300–400ms 稳住，比默认 0.1 略沉一点 */
const LERP = 0.09;
/** Windows 一格滚轮 100px 偏肉，略放大到跟手 */
const WHEEL_MULTIPLIER = 1.15;
/** 连续这么多帧没有实例在滚，就把 rAF 停掉 */
const IDLE_FRAMES = 6;

const instances = new Map<HTMLElement, Lenis>();
/** 模态层的暂停用计数：两个模态嵌套时，先关的那个不能把后关的暂停解掉 */
let pauseDepth = 0;
let observer: MutationObserver | null = null;
let rafId = 0;
let idleFrames = 0;
const pendingScan = new Set<Element>();
const pendingResize = new Set<HTMLElement>();
let scanTimer = 0;
let resizeTimer = 0;

/** Mac 触控板自带惯性，再套一层会「滑过头」；reduce 交给 Lenis 自己的 respectReducedMotion */
function shouldSkip(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}

/* ---------------- 单一 rAF ---------------- */

function pump(time: number): void {
  rafId = 0;
  let active = false;
  instances.forEach((lenis) => {
    lenis.raf(time);
    if (lenis.isScrolling) active = true;
  });
  idleFrames = active ? 0 : idleFrames + 1;
  if (instances.size > 0 && idleFrames < IDLE_FRAMES) rafId = requestAnimationFrame(pump);
}

/** 有新的滚动意图时把循环叫醒（autRaf:false 下没人调用 raf 就完全不动） */
function kick(): void {
  if (rafId) return;
  idleFrames = 0;
  rafId = requestAnimationFrame(pump);
}

/* ---------------- 边界放行 ---------------- */

function handOff(node: Element): void {
  if (node.hasAttribute("data-lenis-prevent")) return;
  node.setAttribute("data-lenis-prevent", "");
  window.setTimeout(() => node.removeAttribute("data-lenis-prevent"), 0);
}

function onWheel(event: WheelEvent): void {
  kick();
  if (event.ctrlKey || event.metaKey) return;
  if (!event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const box = target.closest(SELECTOR);
  if (!(box instanceof HTMLElement) || !instances.has(box)) return;
  const max = box.scrollHeight - box.clientHeight;
  // 容器本来就不能滚（内容比视口短），这格直接交给页面
  if (max <= 0) {
    handOff(target);
    return;
  }
  const atTop = box.scrollTop <= 0;
  const atBottom = box.scrollTop >= max - 1;
  if ((event.deltaY < 0 && atTop) || (event.deltaY > 0 && atBottom)) handOff(target);
}

/* ---------------- 接管与销毁 ---------------- */

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
    // 边界那格由 onWheel 临时打 data-lenis-prevent 放行，这里不再靠 overscroll
    overscroll: true,
    autoRaf: false,
    // 容器里自己滚的块（代码块、图片条）交还给浏览器，别被外层吃掉
    prevent: (node) => node instanceof HTMLElement && Boolean(node.closest("[data-lenis-prevent]")),
  });
  if (pauseDepth > 0) lenis.stop();
  instances.set(el, lenis);
}

function scan(root: ParentNode): void {
  if (root instanceof HTMLElement && root.matches(SELECTOR)) create(root);
  root.querySelectorAll?.(SELECTOR).forEach((node) => {
    if (node instanceof HTMLElement) create(node);
  });
}

function flush(): void {
  scanTimer = 0;
  const roots = Array.from(pendingScan);
  pendingScan.clear();
  roots.forEach((root) => scan(root));

  for (const [el, lenis] of instances) {
    if (el.isConnected) continue;
    lenis.destroy();
    instances.delete(el);
  }

  if (!pendingResize.size) return;
  const boxes = Array.from(pendingResize);
  pendingResize.clear();
  // 追加行不改变容器的盒子尺寸，ResizeObserver 收不到，可滚范围得自己重算
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    boxes.forEach((el) => {
      if (el.isConnected) instances.get(el)?.resize();
    });
  }, 80);
}

function onMutations(records: MutationRecord[]): void {
  let dirty = false;
  for (const record of records) {
    if (record.type === "childList") {
      record.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        const el = node as Element;
        pendingScan.add(el);
        const box = el.closest(SELECTOR);
        if (box instanceof HTMLElement) pendingResize.add(box);
        dirty = true;
      });
    }
    // 流式输出改的是文本节点：容器盒子不变、可滚范围在长，按最近的容器重算
    const target = record.target instanceof Element ? record.target : record.target.parentElement;
    const box = target?.closest?.(SELECTOR);
    if (box instanceof HTMLElement && instances.has(box)) {
      pendingResize.add(box);
      dirty = true;
    }
  }
  if (!dirty || scanTimer) return;
  scanTimer = window.setTimeout(flush, 120);
}

function install(): void {
  if (observer) return;
  scan(document);
  observer = new MutationObserver(onMutations);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  document.addEventListener("wheel", onWheel, { capture: true, passive: true });
}

function destroy(): void {
  document.removeEventListener("wheel", onWheel, { capture: true });
  observer?.disconnect();
  observer = null;
  window.clearTimeout(scanTimer);
  window.clearTimeout(resizeTimer);
  scanTimer = 0;
  pendingScan.clear();
  pendingResize.clear();
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  idleFrames = 0;
  instances.forEach((lenis) => lenis.destroy());
  instances.clear();
  pauseDepth = 0;
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
 * 程序化滚动到某个位置。
 *
 * 直接赋 scrollTop 会被 Lenis 的惯性拉回去（它每帧都在写自己的位置），
 * 走 Lenis.scrollTo(immediate) 才是同一个坐标系里的写法。
 */
export function scrollInstant(el: HTMLElement | null, top: number): void {
  if (!el) return;
  const lenis = instances.get(el);
  if (!lenis) {
    el.scrollTo({ top, behavior: "instant" as ScrollBehavior });
    return;
  }
  lenis.scrollTo(top, { immediate: true });
  kick();
}

/**
 * 模态层打开时暂停：确认框、灯箱盖住整页，底下的侧栏不该还能被滚。
 * Lenis 的 stop() 只是停积分，不动容器样式（autoToggle 才改 overflow）。
 * 用计数而不是布尔：两个模态嵌套时，先关的那个不能把后关的暂停解掉。
 */
export function usePauseSidebarScroll(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    pauseDepth += 1;
    instances.forEach((lenis) => lenis.stop());
    return () => {
      pauseDepth = Math.max(0, pauseDepth - 1);
      if (pauseDepth === 0) instances.forEach((lenis) => lenis.start());
    };
  }, [active]);
}
