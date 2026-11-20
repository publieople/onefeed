import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useGridFreeze } from "./gridFreeze";

/**
 * 每行卡片数：按**内容列实测宽度**算，不看视口断点。
 *
 * 左右两侧的栏一落地，视口 1440 时中间只剩一千出头，xl:3 这类断点会把
 * 三张 216px 都放不下的卡硬塞进三列。所以宽度取自网格自身（ResizeObserver），
 * 侧栏开合、窗口缩放都走同一条路。
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
  width: number;
}

export function useGridCols(): GridCols {
  const [choice, setChoiceState] = useState<ColsChoice>(readChoice);
  const [width, setWidth] = useState<number>(initialWidth);
  // 挂到网格那层（<section>），它的内容宽度就是卡片可用的总宽
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const next = el.clientWidth;
      if (next > 0) setWidth(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const setChoice = useCallback((next: ColsChoice) => {
    setChoiceState(next);
    writeChoice(next);
  }, []);

  // 侧栏补间期间用冻结的目标宽度算列数，避免中途 3 列→4 列→3 列地翻
  const frozen = useGridFreeze();
  const effective = frozen ?? width;
  const maxFit = maxFitCols(effective);
  const cols =
    choice === "auto" ? Math.min(autoColsFor(effective), maxFit) : Math.min(choice, maxFit);

  return { ref, choice, setChoice, cols, maxFit, width };
}