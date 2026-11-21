import { useEffect } from "react";
import { isPageScrollLocked } from "./useScrollLock";

/**
 * 全站滚轮缓动：立刻跟手 + 余量滑行。
 *
 * 为什么不再用 Lenis：它是纯位置缓动（lerp 0.09），一格滚轮要 300–400ms 才走完，
 * 而且事件当帧一步都不走。实测 100px 一格：首帧才 8px、840ms 才停住，
 * 连续滚是「黏着往前爬」，不是「滑」。
 *
 * 这里改成两段：
 * 1. 滚轮事件当帧就把 delta 的一大半（IMMEDIATE）直接写进 scrollTop —— 眼睛立刻有反馈；
 * 2. 剩下的差额按指数缓动收尾（TAU_MS 约 70ms 走掉 63%，200ms 内停稳），所以还有余速，
 *    但不会像 Lenis 那样拖到 800ms。
 * 再加每帧位移上限 MAX_SPEED × dt：掉帧时不会一帧跳 150px（旧实现实测 890→986）。
 *
 * 页面本体和侧栏共用一套引擎。原来页面走 useScrollSpeedCap 的「匀速放行」，
 * 只有限速没有缓动，Windows 一格 100px 就是阶梯；统一之后两边手感一致。
 *
 * 不接管的：Mac（触控板自带惯性，再套一层会滑过头）、prefers-reduced-motion、
 * Ctrl/⌘+滚轮（缩放）、横向滚轮、其它自有滚动容器（评论列表等）。
 */

const SELECTOR = "[data-smooth-scroll]";
/** 一格滚轮里立刻走掉的比例。0.62 ≈ 当帧就走一半以上，剩下的才滑 */
const IMMEDIATE = 0.62;
/** 余量的时间常数（ms）：55ms 走掉 63%，280ms 内基本停住 */
const TAU_MS = 55;
/** Windows 一格 100px 偏肉，略放大到跟手 */
const WHEEL_MULTIPLIER = 1.15;
/** 每帧最多走 MAX_SPEED × dt 像素，掉帧时不许一帧跳一大段 */
const MAX_SPEED = 2000;
/** dt 上限：切标签页回来时差值是几百 ms，不能一次补完；也顺带把单帧上限定在 64px 左右 */
const MAX_DT = 0.032;
/** 连续这么多帧没有目标在动，就把 rAF 停掉（空闲时 0 回调） */
const IDLE_FRAMES = 6;
/** 余量小于这个值直接对齐，别让 rAF 永远差 0.3px 不休息 */
const EPSILON = 0.4;

interface Surface {
  /** null = 页面本体（document.scrollingElement） */
  el: HTMLElement | null;
  current: number;
  target: number;
}

const boxes = new Map<HTMLElement, Surface>();
const page: Surface = { el: null, current: 0, target: 0 };
let pauseDepth = 0;
let rafId = 0;
let idleFrames = 0;
let lastTime = 0;

function shouldSkip(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true;
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}

function nodeOf(surface: Surface): HTMLElement | null {
  return surface.el ?? (document.scrollingElement as HTMLElement | null);
}

function readPos(surface: Surface): number {
  return nodeOf(surface)?.scrollTop ?? 0;
}

function maxPos(surface: Surface): number {
  const node = nodeOf(surface);
  if (!node) return 0;
  // 信息流会一直追加，最大值每次现算，别缓存
  return Math.max(0, node.scrollHeight - node.clientHeight);
}

function writePos(surface: Surface, top: number): void {
  const node = nodeOf(surface);
  if (!node) return;
  // 容器上有 scroll-behavior: smooth（留给键盘翻页），直接赋 scrollTop 会被浏览器
  // 当成一次平滑滚动 —— 每帧只挪 2px，滚轮就成「爬」了。必须显式 instant。
  node.scrollTo({ top, behavior: "instant" as ScrollBehavior });
}

function surfaceFor(el: HTMLElement): Surface {
  let surface = boxes.get(el);
  if (!surface) {
    const top = el.scrollTop;
    surface = { el, current: top, target: top };
    boxes.set(el, surface);
    prune();
  }
  return surface;
}

/** 卸载的列表会留下死引用，偶尔清一次就够 */
function prune(): void {
  if (boxes.size < 16) return;
  for (const [el, surface] of boxes) {
    if (el.isConnected) continue;
    // 先对齐到真实位置，避免拿旧 target 把新页面拽走
    surface.current = 0;
    surface.target = 0;
    boxes.delete(el);
  }
}

function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

/** 事件目标在不在一个「自己的」滚动容器里：在的话这一格不该由页面消费 */
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

/* ---------------- 循环 ---------------- */

function frame(time: number): void {
  rafId = 0;
  const dt = lastTime ? Math.min(MAX_DT, Math.max(0, time - lastTime) / 1000) : 1 / 60;
  lastTime = time;
  const ease = 1 - Math.exp((-dt * 1000) / TAU_MS);
  const cap = MAX_SPEED * dt;
  const all: Surface[] = [page, ...boxes.values()];
  let active = false;

  for (const surface of all) {
    // 模态层锁住整页时，页面不许再被余量拖着走
    if (surface === page && isPageScrollLocked()) {
      surface.target = surface.current = readPos(surface);
      continue;
    }
    // 别人把位置改了（路由切换的 scrollTo(0)、键盘翻页、scrollIntoView）：
    // 以真实位置为准，别拿旧 target 把人拽回去
    const actual = readPos(surface);
    if (Math.abs(actual - surface.current) > 2) {
      surface.current = actual;
      surface.target = actual;
      continue;
    }
    const diff = surface.target - surface.current;
    if (Math.abs(diff) < EPSILON) {
      if (diff) writePos(surface, (surface.current = surface.target));
      continue;
    }
    const step = clamp(diff * ease, -cap, cap);
    surface.current += step;
    writePos(surface, surface.current);
    active = true;
  }

  idleFrames = active ? 0 : idleFrames + 1;
  if (idleFrames < IDLE_FRAMES) {
    rafId = requestAnimationFrame(frame);
  } else {
    rafId = 0;
    lastTime = 0;
  }
}

function kick(): void {
  if (rafId) return;
  idleFrames = 0;
  requestAnimationFrame((time) => {
    lastTime = time;
    frame(time);
  });
}

/* ---------------- 滚轮 ---------------- */

function push(surface: Surface, delta: number): void {
  // 上一次已经停稳：以真实位置为准重新对齐（键盘翻页、程序化滚动都会把它挪走）
  if (Math.abs(surface.target - surface.current) < EPSILON) {
    const actual = readPos(surface);
    surface.current = actual;
    surface.target = actual;
  }
  const max = maxPos(surface);
  surface.target = clamp(surface.target + delta, 0, max);
  // 立刻跟手：这一格的一大半当帧就写进去
  surface.current = clamp(surface.current + delta * IMMEDIATE, 0, max);
  writePos(surface, surface.current);
  kick();
}

function onWheel(event: WheelEvent): void {
  if (event.ctrlKey || event.metaKey) return;
  if (!event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
  if (pauseDepth > 0 || isPageScrollLocked()) {
    // 模态层盖住整页：谁的滚轮都别吃，也别让底下的侧栏跟着动
    event.preventDefault();
    return;
  }

  const origin = event.target instanceof Element ? event.target : null;
  const box = origin?.closest(SELECTOR);
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
  const delta = event.deltaY * unit * WHEEL_MULTIPLIER;
  const boxSurface = box instanceof HTMLElement ? surfaceFor(box) : null;

  // 别的滚动容器（评论列表等）交还给浏览器
  if (!boxSurface && ownsScroll(event.target)) return;

  // 侧栏到底/到顶：这一格顺着滚动链交给页面，同一个引擎滚，免得两套缓动打架
  let surface = boxSurface ?? page;
  if (boxSurface) {
    const max = maxPos(boxSurface);
    const atTop = boxSurface.current <= 0.5;
    const atBottom = boxSurface.current >= max - 0.5;
    if ((delta < 0 && atTop) || (delta > 0 && atBottom)) surface = page;
  }
  if (surface === page) {
    const max = maxPos(page);
    // 页面本来就没得滚：别吞这一格
    if ((delta < 0 && page.current <= 0.5) || (delta > 0 && page.current >= max - 0.5)) return;
  }

  event.preventDefault();
  push(surface, delta);
}

/* ---------------- 安装 ---------------- */

let installed = false;

function install(): void {
  if (installed) return;
  installed = true;
  document.addEventListener("wheel", onWheel, { capture: true, passive: false });
}

function destroy(): void {
  document.removeEventListener("wheel", onWheel, { capture: true });
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  idleFrames = 0;
  lastTime = 0;
  boxes.clear();
  page.current = 0;
  page.target = 0;
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
 *
 * 交给引擎写，并把 current/target 一起对齐 —— 否则下一帧它会拿旧 target 把人拽回去。
 */
export function scrollInstant(el: HTMLElement | null, top: number): void {
  if (!el) return;
  const surface = surfaceFor(el);
  surface.current = top;
  surface.target = top;
  writePos(surface, top);
}

/**
 * 模态层打开时暂停：确认框、灯箱盖住整页，底下的侧栏不该还能被滚。
 * 用计数而不是布尔：两个模态嵌套时，先关的那个不能把后关的暂停解掉。
 */
export function usePauseSidebarScroll(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    pauseDepth += 1;
    return () => {
      pauseDepth = Math.max(0, pauseDepth - 1);
    };
  }, [active]);
}
