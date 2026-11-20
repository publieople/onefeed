import { useCallback, useLayoutEffect, useRef, useState } from "react";

/**
 * 每行卡片数：**只在窗口尺寸变化时重算，侧栏开合不参与**。
 *
 * 曾经的写法是盯网格自身的宽度（ResizeObserver）：左栏一收，内容列宽 +176px，
 * 3 列 370 的卡当场翻成 4 列 317 —— 用户点一下侧栏，整屏卡片重排一次。
 * 列数是版式契约，不该被一次开合改写。中间还试过「补间期间冻结目标宽度」，
 * 治的只是动画那 300ms，补间一结束照样翻，等于没治。
 *
 * 现在：宽度只在窗口 resize / 挂载时量一次；侧栏开合期间卡片宽度随 1fr 连续变化，
 * 列数不动，卡片变胖变瘦但不换行 —— 这正是「侧栏推拉、内容不动」的观感。
 *
 * 一个例外：挂载后再补量一次（SETTLE_MS）。右栏是带宽度动画开出来的，
 * 挂载那一刻内容列还是全宽，等动画落定再抓一次真实宽度，免得带着右栏刷新时
 * 一直按全宽算列数。补量只发生一次，与用户开合侧栏无关。
 *
 * 选择存 localStorage 而不是 URL：URL 是可分享的筛选状态，列数是设备偏好。
 */

export type ColsChoice = "auto" | 1 | 2 | 3 | 4 | 5;

const STORAGE_KEY = "onefeed.feed.cols";
/** 与网格的 gap-x-5 一致 */
export const GRID_GAP = 20;
/** 再窄就不是卡片了：标题放不下两个字，meta 折行 */
export const CARD_MIN = 216;
/** 「自动」的目标卡宽：舒适阅读的上限 */
const CARD_TARGET = 330;
const MAX_COLS = 5;
/** 挂载后补量一次真实宽度的时间点：右栏宽度补间 260ms + 余量 */
const SETTLE_MS = 420;

function readChoice(): ColsChoice {
  if (typeof localStorage === "undefined") return "auto";
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === "auto") return "auto";
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 && n <= MAX_COLS ? (n as ColsChoice) : "auto";
}

function writeChoice(choice: ColsChoice): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(choice));
  } catch {
    // 隐私模式写不进去就算了，本次会话照样生效
  }
}

export function maxFitCols(width: number): number {
  if (width <= 0) return 1;
  return Math.max(1, Math.min(MAX_COLS, Math.floor((width + GRID_GAP) / (CARD_MIN + GRID_GAP))));
}

export function autoColsFor(width: number): number {
  if (width <= 0) return 1;
  // 向下取整：900 宽的窗口 852 / 330 = 2.58，四舍五入会硬塞成 3 列、每列只剩 270，
  // 标题两个字就开始折行。宁可少一列，卡片宽度先够。
  return Math.min(MAX_COLS, Math.max(1, Math.floor(width / CARD_TARGET)));
}

/**
 * 首帧先用 main 的实测宽度垫底，免得挂载时先按 1 列画一遍再跳成 3 列
 * （那一下跳动比列数本身更刺眼）。
 */
function initialWidth(): number {
  if (typeof document === "undefined") return 1120;
  const column = document.querySelector("[data-content]");
  if (column) return column.clientWidth || 1120;
  const main = document.getElementById("main");
  const w = main ? main.clientWidth - 48 : window.innerWidth - 48;
  return w > 0 ? w : 1120;
}

export interface GridCols {
  /** 挂到网格元素上，用来量宽度 */
  ref: React.RefObject<HTMLElement>;
  choice: ColsChoice;
  setChoice: (choice: ColsChoice) => void;
  /** 实际渲染的列数（选择值可能被宽度收住） */
  cols: number;
  /** 这个宽度最多能放几列 */
  maxFit: number;
  /** 计列用的宽度：窗口尺寸决定，不随侧栏开合变化 */
  width: number;
}

export function useGridCols(): GridCols {
  const [choice, setChoiceState] = useState<ColsChoice>(readChoice);
  const [width, setWidth] = useState<number>(initialWidth);
  // 挂到网格那层（<section>），它的宽度就是卡片可用的总宽
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const next = el.clientWidth;
      if (next > 0) setWidth(next);
    };
    // 挂载时量一次，等布局落定
    let frame = requestAnimationFrame(measure);
    // 窗口尺寸变了才重量；网格自身变宽变窄（侧栏开合）故意不监听 ——
    // 这正是「点侧栏整屏重排」的来源。
    const onResize = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onResize);
    // 右栏开栏动画结束后补量一次，把落定后的真实宽度抓进来
    const settle = window.setTimeout(measure, SETTLE_MS);
    return () => {
      window.removeEventListener("resize", onResize);
      window.clearTimeout(settle);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  const setChoice = useCallback((next: ColsChoice) => {
    setChoiceState(next);
    writeChoice(next);
  }, []);

  const maxFit = maxFitCols(width);
  const cols = choice === "auto" ? Math.min(autoColsFor(width), maxFit) : Math.min(choice, maxFit);

  return { ref, choice, setChoice, cols, maxFit, width };
}
