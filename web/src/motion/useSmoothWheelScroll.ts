import Lenis from "lenis";
import { useEffect } from "react";
import { isPageScrollLocked } from "./useScrollLock";

/**
 * 全站滚轮缓动：页面本体 + 侧栏共用一套 Lenis 实例参数。
 *
 * 参数来自 2026-11-21 的九宫格对照（.onefeed/tmp/scroll-preview/index.html 的 3 号面板）：
 * duration 0.85 + easeOutQuart + wheelMultiplier 1。
 * 同样滚一格 100px，实测 38 帧、最大单步 6px、613ms 收住；旧的两段式引擎是 15 帧、
 * 单步 71px —— 那就是「先跳一下再滑」的来源。
 *
 * 三条约束：
 * 1. Lenis 1.3 的 autoRaf 默认 false，必须自己喂 raf；这里用一个循环驱动全部实例，
 *    谁都不滚了就把 rAF 停掉（空闲 0 回调）。
 * 2. 侧栏到顶/到底继续滚时，要把这一格交给页面。Lenis 自己的 overscroll 链是
 *    「不 preventDefault 让浏览器原生滚」，会跳；所以容器 capture 阶段拦下，
 *    改成给页面实例 scrollTo(target + delta)，两段都还是同一套缓动。
 * 3. 模态层（确认框、灯箱、收藏对话框）打开时谁都不许动，在 document capture 阶段吞掉。
 *
 * 不接管：Mac（触控板自带惯性）、prefers-reduced-motion、Ctrl/⌘+滚轮（缩放）。
 */

const SELECTOR = "[data-smooth-scroll]";
/** 一段滚轮动画的时长（秒）。0.85 在 100px 一格时约 610ms 收住 */
const DURATION = 0.85;
/** Windows 一格 100px 已经够，不再放大 */
const WHEEL_MULTIPLIER = 1;
/** easeOutQuart：起手快、尾巴收得干脆 */
const EASING = (t: number): number => 1 - Math.pow(1 - t, 4);
/** 连续这么多帧没有实例在滚，就把 rAF 停掉 */
const IDLE_FRAMES = 6;

const boxes = new Map<HTMLElement, Lenis>();
let pageLenis: Lenis | null = null;
let rafId = 0;
let idleFrames = 0;
let pauseDepth = 0;
let installed = false;
let observer: MutationObserver | null = null;
let resizeTimer = 0;

function shouldSkip(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}

function options(): ConstructorParameters<typeof Lenis>[0] {
  return {
    duration: DURATION,
    easing: EASING,
    wheelMultiplier: WHEEL_MULTIPLIER,
    smoothWheel: true,
    overscroll: false,
    autoRaf: false,
  };
}

/* ---------------- 循环 ---------------- */

function frame(time: number): void {
  rafId = 0;
  let active = false;
  if (pageLenis) {
    pageLenis.raf(time);
    if (pageLenis.isScrolling) active = true;
  }
  for (const lenis of boxes.values()) {
    lenis.raf(time);
    if (lenis.isScrolling) active = true;
  }
  idleFrames = active ? 0 : idleFrames + 1;
  if (idleFrames < IDLE_FRAMES) {
    rafId = requestAnimationFrame(frame);
  }
}

function kick(): void {
  if (rafId) return;
  idleFrames = 0;
  rafId = requestAnimationFrame(frame);
}

/* ---------------- 侧栏边界 -> 页面 ---------------- */

function wheelPx(event: WheelEvent, el: HTMLElement): number {
  const unit =
    event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? el.clientHeight : 1;
  return event.deltaY * unit;
}

function pageLimit(): number {
  const doc = document.scrollingElement ?? document.documentElement;
  return Math.max(0, doc.scrollHeight - window.innerHeight);
}

function forwardToPage(delta: number): void {
  if (!pageLenis) return;
  const base = Number.isFinite(pageLenis.targetScroll) ? pageLenis.targetScroll : window.scrollY;
  const next = Math.max(0, Math.min(pageLimit(), base + delta));
  pageLenis.scrollTo(next, { duration: DURATION, easing: EASING, lock: true });
  kick();
}

/** 容器上的 capture：只处理「已经到边、还继续往外滚」的那一格 */
function onBoxWheel(event: WheelEvent): void {
  if (event.ctrlKey || event.metaKey || !event.deltaY) return;
  if (pauseDepth > 0 || isPageScrollLocked()) return;
  const box = event.currentTarget as HTMLElement;
  const delta = wheelPx(event, box);
  if (!delta || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
  const max = Math.max(0, box.scrollHeight - box.clientHeight);
  const atTop = box.scrollTop <= 0.5;
  const atBottom = box.scrollTop >= max - 0.5;
  if (!((delta < 0 && atTop) || (delta > 0 && atBottom))) return;
  // 拦住这一格，别让容器实例再吃一遍，也别让浏览器原生滚
  event.preventDefault();
  event.stopImmediatePropagation();
  forwardToPage(delta);
}

/* ---------------- 全站闸门 ---------------- */

function onWheelCapture(event: WheelEvent): void {
  kick();
  if (pauseDepth > 0 || isPageScrollLocked()) {
    event.preventDefault();
    event.stopPropagation();
  }
}

/* ---------------- 实例管理 ---------------- */

function attach(el: HTMLElement): void {
  if (boxes.has(el)) return;
  const lenis = new Lenis({ ...options(), wrapper: el, content: el });
  boxes.set(el, lenis);
  el.addEventListener("wheel", onBoxWheel, { capture: true, passive: false });
}

function detach(el: HTMLElement): void {
  const lenis = boxes.get(el);
  if (!lenis) return;
  el.removeEventListener("wheel", onBoxWheel, { capture: true });
  lenis.destroy();
  boxes.delete(el);
}

function scan(): void {
  if (!installed) return;
  const found = new Set(document.querySelectorAll<HTMLElement>(SELECTOR));
  for (const el of found) attach(el);
  for (const el of [...boxes.keys()]) if (!found.has(el)) detach(el);
  // 列表长度变了，limit 要重算
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    for (const lenis of boxes.values()) lenis.resize();
  }, 120);
}

function install(): void {
  if (installed) return;
  installed = true;
  pageLenis = new Lenis({
    ...options(),
    // 侧栏里的滚轮归侧栏实例，页面别跟着滚
    prevent: (node) =>
      node instanceof Element && !!node.closest(SELECTOR),
  });
  document.addEventListener("wheel", onWheelCapture, { capture: true, passive: false });
  observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.addedNodes.length || record.removedNodes.length) {
        scan();
        return;
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  scan();
}

function destroy(): void {
  document.removeEventListener("wheel", onWheelCapture, { capture: true });
  observer?.disconnect();
  observer = null;
  for (const el of [...boxes.keys()]) detach(el);
  pageLenis?.destroy();
  pageLenis = null;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  idleFrames = 0;
  pauseDepth = 0;
  installed = false;
}

/** 在 App 里挂一次：页面本体 + 所有 [data-smooth-scroll] 容器都走这套缓动 */
export function useSmoothWheelScroll(): void {
  useEffect(() => {
    if (shouldSkip()) return;
    install();
    return destroy;
  }, []);
}

/**
 * 程序化滚动到某个位置（对话流吸底用）。
 * 有实例就交给它 immediate 跳过去，否则直接写 scrollTop。
 */
export function scrollInstant(el: HTMLElement | null, top: number): void {
  if (!el) return;
  const lenis = boxes.get(el);
  if (lenis) {
    lenis.scrollTo(top, { immediate: true });
    kick();
    return;
  }
  el.scrollTo({ top, behavior: "instant" as ScrollBehavior });
}

/**
 * 模态层打开时暂停：确认框、灯箱盖住整页，底下的页面与侧栏都不该还能被滚。
 * 用计数而不是布尔：两个模态嵌套时，先关的那个不能把后关的暂停解掉。
 */
export function usePauseSidebarScroll(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    pauseDepth += 1;
    pageLenis?.stop();
    for (const lenis of boxes.values()) lenis.stop();
    return () => {
      pauseDepth = Math.max(0, pauseDepth - 1);
      if (pauseDepth === 0) {
        pageLenis?.start();
        for (const lenis of boxes.values()) lenis.start();
      }
    };
  }, [active]);
}
