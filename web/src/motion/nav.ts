import { flushSync } from "react-dom";

/**
 * 跳页时套一层 View Transition。
 *
 * 和第一版（navTransition.ts）的差别：
 * - 可以共享**多个**元素（媒体框、标题…），不再只有整张大卡片；
 * - 加了并发令牌：连点两张卡片，第二次直接瞬切，不会出现前一次的清场把后一次的
 *   名字一起抹掉（那会让浏览器把整页当成一个元素乱飞）；
 * - 按场景分组（push/back/tab/lightbox/filter），CSS 里各组走各自的动画。
 */

type Doc = Document & {
  startViewTransition?: (callback: () => void) => { finished: Promise<void> };
};

export type NavKind = "push" | "back" | "tab" | "lightbox" | "filter" | "plain";

export interface NavName {
  el: Element | null;
  name: string;
}

export interface NavOpts {
  /** 参与变形的元素。最多 3 个；重名会被丢掉（重名会让浏览器整体降级成根转场） */
  names?: NavName[];
}

/** 正在跑的那一次，用来做并发保护与清场 */
let inflight: { seq: number; els: HTMLElement[]; classes: string[] } | null = null;
let seq = 0;

const MAX_NAMES = 3;

function collect(opts: NavOpts): { el: HTMLElement; name: string }[] {
  const out: { el: HTMLElement; name: string }[] = [];
  const seen = new Set<string>();
  const push = (el: Element | null | undefined, name: string) => {
    if (!el || out.length >= MAX_NAMES) return;
    if (seen.has(name)) return;
    seen.add(name);
    out.push({ el: el as HTMLElement, name });
  };
  for (const n of opts.names ?? []) push(n.el, n.name);
  return out;
}

/**
 * 详情页的共享元素名字是常驻的（否则新页快照时来不及挂上）。
 * 从详情页往「不相干」的页面走时，这些名字会让浏览器把媒体框和标题当成要飞过去的元素，
 * 于是屏幕上先飘一下再消失。这种跳转前把它们摘掉。
 */
function clearStrayNames(keep: Element[]): void {
  const kept = new Set(keep);
  document.querySelectorAll<HTMLElement>("[data-vt]").forEach((el) => {
    if (kept.has(el)) return;
    if (el.dataset.vt === "topbar") return; // 顶栏本来就要独立成层，一直挂着
    el.style.viewTransitionName = "";
  });
}

function clearState(st: { els: HTMLElement[]; classes: string[] }): void {
  for (const el of st.els) {
    // 元素可能已经被 React 卸载了，改样式会静默失败甚至报错，吞掉
    try {
      el.style.viewTransitionName = "";
    } catch {
      /* ignore */
    }
  }
  const root = document.documentElement;
  for (const c of st.classes) root.classList.remove(c);
}

/**
 * 跑一次带转场的跳转。
 * 浏览器不支持、或用户开了「减少动态效果」时不跳动画，但**交互照常**（只是没有过渡）。
 */
export function runNav(kind: NavKind, apply: () => void, opts: NavOpts = {}): void {
  const doc = document as Doc;
  const reduce =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || typeof doc.startViewTransition !== "function") {
    apply();
    return;
  }

  // 上一次还没走完：不排队（排队会让连点变成慢动作），清掉它留下的状态直接瞬切
  if (inflight) {
    clearState(inflight);
    inflight = null;
    apply();
    return;
  }

  const named = collect(opts);
  const root = document.documentElement;
  const classes = ["nav-vt", `nav-vt-${kind}`];
  if (kind === "back") classes.push("nav-vt-back");

  // 去一个跟详情页没有任何共享元素的页面：先摘掉常驻名字，别让媒体框无家可归地飘走
  if (kind === "plain") clearStrayNames(named.map((n) => n.el));
  // 转场期间锁住滚动：否则动画跑到一半用户一滚，快照和实际位置就对不上了
  root.classList.add("vt-running");

  for (const item of named) item.el.style.viewTransitionName = item.name;
  for (const c of classes) root.classList.add(c);

  const st = { seq: ++seq, els: named.map((n) => n.el), classes };
  inflight = st;

  let ran = false;
  const run = () => {
    if (ran) return;
    ran = true;
    // React 默认批处理更新，快照可能拿到旧 DOM；强制同帧提交
    flushSync(apply);
  };
  const done = () => {
    clearState(st);
    document.documentElement.classList.remove("vt-running");
    if (inflight === st) inflight = null;
  };

  try {
    const vt = doc.startViewTransition(run);
    void vt.finished.then(done, done);
  } catch {
    run();
    done();
  }
}

/** 有没有一次转场正在进行（滚动锁定、预取要避开它） */
export function navBusy(): boolean {
  return inflight !== null;
}
