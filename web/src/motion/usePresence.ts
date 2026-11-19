import { useEffect, useState } from "react";

/**
 * 出现和收起都留出过渡时间。
 *
 * 出现：直接挂载、直接就是「展开态」，进场交给 CSS @keyframes（.sheet-in / .drawer-in）。
 * 这里不再用「先渲染收起态、下一拍再切展开态」的写法 —— 主线程一忙，两次 setState
 * 会被合并成一帧，元素一出生就是终态，过渡根本没有起点（2026-11-19 实测，
 * 抽屉和底部抽屉都因此变成硬切）。
 *
 * 收起：切回收起态让 CSS transition 跑，ms 之后再卸载。
 * 不用 AnimatePresence / rAF 收尾：标签页不可见时动画帧会被节流到 ~1fps，
 * 退场回调可能永远不来，面板就卡在 DOM 里关不掉（2026-11-18 踩过）。
 */
export function usePresence(open: boolean, ms = 240) {
  const [keep, setKeep] = useState(open);

  useEffect(() => {
    if (open) {
      setKeep(true);
      return;
    }
    const leave = window.setTimeout(() => setKeep(false), ms);
    return () => window.clearTimeout(leave);
  }, [open, ms]);

  return { mounted: open || keep, shown: open };
}
