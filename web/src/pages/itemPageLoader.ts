import type { ComponentType } from "react";
import type { OutletCtx } from "../App";

/**
 * 详情页按需加载。
 *
 * 主包以前把 FeedPage 和 ItemPage 一起静态引进来，首屏要背详情页的代码：
 * 灯箱、收藏对话框、评论树、摘要渲染全在里面，单包 519KB。评审实测 Fast 3G + 4× CPU
 * 下首卡 9.4s、LCP 9224ms，其中很大一段是先把用不到的详情页下完。
 *
 * 但共享元素转场要求「点下去之后立刻能拿到新快照」，所以不能纯靠 React.lazy 的兜底：
 * 卡片悬停 / 按下就先 import() 预热，真点到冷卡时这里等模块就位再起转场，
 * 绝不会把 Suspense 骨架拍进 View Transition 的快照里。
 */
let pending: Promise<unknown> | null = null;
let loaded = false;

export function loadItemPage(): Promise<unknown> {
  if (!pending) {
    pending = import("./ItemPage").then((mod) => {
      loaded = true;
      return mod;
    });
  }
  return pending;
}

export function itemPageLoaded(): boolean {
  return loaded;
}

/** React.lazy 需要 { default: ComponentType }，这里把同一个 promise 复用掉。 */
export async function loadItemPageComponent(): Promise<{ default: ComponentType<{ ctx?: OutletCtx }> }> {
  const mod = (await loadItemPage()) as { default: ComponentType<{ ctx?: OutletCtx }> };
  return { default: mod.default };
}
