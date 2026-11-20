import { useSyncExternalStore } from "react";

/**
 * 补间期间把网格列数钉在**目标宽度**算出来的那一档。
 *
 * 侧栏宽度补间 260ms，内容列每帧都被 ResizeObserver 量一次：3 列 370px 的卡
 * 会先被拉宽到 426，中途跨过 4 列的门槛，再塌成 317 —— 一帧里两次变宽。
 * 这里在补间开始时按目标宽度定一次列数，补间结束后再交回实测值。
 *
 * 存的是「目标内容宽度」而不是列数：列数还取决于用户选的 auto/固定几列，
 * 那属于 useGridCols 的判断，这里只负责在那段时间里替它看一个稳定宽度。
 */

const MAX_CONTENT = 1400;

let frozen: number | null = null;
let timer = 0;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((fn) => fn());
}

export function freezeGridWidth(width: number, ms = 340): void {
  if (!(width > 0)) return;
  frozen = Math.min(width, MAX_CONTENT);
  emit();
  if (timer) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    timer = 0;
    frozen = null;
    emit();
  }, ms);
}

export function clearGridFreeze(): void {
  if (timer) window.clearTimeout(timer);
  timer = 0;
  if (frozen === null) return;
  frozen = null;
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** 冻结中的目标宽度；没有冻结返回 null */
export function useGridFreeze(): number | null {
  return useSyncExternalStore(subscribe, () => frozen, () => null);
}
