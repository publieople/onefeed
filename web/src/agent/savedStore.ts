import { useSyncExternalStore } from "react";

/**
 * 「这条在不在稍后再看里」的细粒度仓库。
 *
 * 早先卡片从会话上下文里读 `saved: Set<string>`，一屏 30 张卡都订阅同一个 Set：
 * 点一颗星 → Set 换新引用 → 30 张卡全部重渲染，实测 160–240ms 的卡顿全花在这上面。
 *
 * 这里把状态拆成 per-id 的布尔值，卡片只订阅自己那条；useSyncExternalStore 的
 * 快照没变就不重渲染 —— 点谁只有谁动。
 */
const flags = new Map<string, boolean>();
const listeners = new Set<() => void>();

export const savedStore = {
  get(id: string): boolean {
    return flags.get(id) === true;
  },
  set(id: string, on: boolean): void {
    if (flags.get(id) === on) return;
    flags.set(id, on);
    for (const listener of listeners) listener();
  },
  toggle(id: string): boolean {
    const next = !savedStore.get(id);
    savedStore.set(id, next);
    return next;
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};

/** 列表数据回来时把 item.saved 灌进来：卡片据此点亮星标，toggle 也才有正确起点 */
export function seedSaved(items: ReadonlyArray<{ id: string; saved?: boolean }>): void {
  for (const item of items) {
    if (item.saved) savedStore.set(item.id, true);
  }
}

export function useIsSaved(id: string): boolean {
  return useSyncExternalStore(
    savedStore.subscribe,
    () => savedStore.get(id),
    () => false,
  );
}
