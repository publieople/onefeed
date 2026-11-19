import { useCallback, useEffect, useState } from "react";

/**
 * 外壳的三块地：左 Agent 工作台、中信息流、右稍后再看 / AI。
 *
 * 断点不是随便定的，都是被「内容列最窄能到多少」逼出来的：
 *   - 1440 起右栏可以钉住 320（默认关着，按 `]` 打开）：窄屏塞进去中列只剩 800 多；
 *   - 1200 起左栏才敢展开到 240：再窄中列会掉到 900 以下，三列卡片挤成一团；
 *   - 960 起退成 64 的图标轨，不占内容宽度，也还认得出来是栏。
 *
 * 左栏只有「宽 / 图标轨 / 不显示」三档，**全部待在栅格里**：点展开就是把这一列的
 * 宽度从 64 换到 240，让内容列自己让位。早先 <1440 时展开是一个 fixed 的全屏浮层，
 * 288 的抽屉压在页面左边、盖住内容，点一次像跳进了另一个页面 —— 沉浸感全没了。
 */

export type LeftLayout = "full" | "rail" | "hidden";
export type RightLayout = "pinned" | "drawer";

const LEFT_KEY = "onefeed.shell.left";
const LEFT_FULL = 1200;
const LEFT_RAIL = 960;
const RIGHT_PIN = 1440;

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

function writeFlag(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* 隐私模式写不进去就算了，只影响下次打开时的默认态 */
  }
}

export interface Shell {
  width: number;
  left: LeftLayout;
  right: RightLayout;
  rightOpen: boolean;
  setRightOpen: (open: boolean) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
}

export function useShell(): Shell {
  const [width, setWidth] = useState(() =>
    typeof window === "undefined" ? LEFT_FULL : document.documentElement.clientWidth,
  );
  // 宽屏默认展开；窄屏默认收成图标轨 —— 先给内容列留够地方
  const [expanded, setExpanded] = useState(() =>
    readFlag(LEFT_KEY, document.documentElement.clientWidth >= LEFT_FULL),
  );
  const pinned = width >= RIGHT_PIN;
  // 右栏默认不占位：信息流要铺满中间，想开的时候自己按 `]`。
  // 它不像左栏是常驻导航，是「稍后再看 / AI」的抽屉，用不到时不该一直吃掉 320。
  const [rightOpen, setRightOpen] = useState(false);
  const [wasPinned, setWasPinned] = useState(pinned);

  useEffect(() => {
    const onResize = () => setWidth(document.documentElement.clientWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // 只有跨过 1440 这条线才动右栏：从宽屏缩回抽屉区必须收起来，
  // 否则 340 的抽屉会盖住半屏；反过来放大成一栏时保持当前开合，不擅自替用户拉开。
  useEffect(() => {
    if (pinned === wasPinned) return;
    setWasPinned(pinned);
    if (!pinned) setRightOpen(false);
  }, [pinned, wasPinned]);

  const left: LeftLayout =
    width >= LEFT_RAIL ? (expanded ? "full" : "rail") : "hidden";

  // 1200 以上是「240 钉住 / 64 图标轨」，960–1199 也走同一条路：点展开就是这一列变宽，
  // 内容列被 flex 自动挤窄，不再有盖住页面的浮层。
  const toggleLeft = useCallback(() => {
    setExpanded((prev) => {
      writeFlag(LEFT_KEY, !prev);
      return !prev;
    });
  }, []);

  const toggleRight = useCallback(() => setRightOpen((prev) => !prev), []);

  return {
    width,
    left,
    right: pinned ? "pinned" : "drawer",
    rightOpen,
    setRightOpen,
    toggleLeft,
    toggleRight,
  };
}