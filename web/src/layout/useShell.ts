import { useCallback, useEffect, useState } from "react";

/**
 * 外壳的三块地：左 Agent 工作台、中信息流、右稍后再看 / AI。
 *
 * 断点不是随便定的，都是被「内容列最窄能到多少」逼出来的：
 *   - 1440 起左栏才敢钉住 288：再窄中列就掉到 1000 以下，3 列卡片会挤成一团；
 *   - 1024 起给 64 的图标轨，不占内容宽度，也还认得出来是栏；
 *   - 1800 起右栏也钉住：1440 段再塞 320 进去，中列只剩 800 多。
 *
 * 左栏只有「宽 / 图标轨 / 不显示」三档，**全部待在栅格里**：点展开就是把这一列的
 * 宽度从 64 换到 288，让内容列自己让位。早先 <1440 时展开是一个 fixed 的全屏浮层，
 * 288 的抽屉压在页面左边、盖住内容，点一次像跳进了另一个页面 —— 沉浸感全没了。
 */

export type LeftLayout = "full" | "rail" | "hidden";
export type RightLayout = "pinned" | "drawer";

const LEFT_KEY = "onefeed.shell.left";
const LEFT_FULL = 1440;
const LEFT_RAIL = 1024;
const RIGHT_PIN = 1800;

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
  // 宽屏默认展开；窄屏默认收成图标轨 —— 1280 上先给内容列留够地方
  const [expanded, setExpanded] = useState(() =>
    readFlag(LEFT_KEY, document.documentElement.clientWidth >= LEFT_FULL),
  );
  const pinned = width >= RIGHT_PIN;
  const [rightOpen, setRightOpen] = useState(pinned);
  const [wasPinned, setWasPinned] = useState(pinned);

  useEffect(() => {
    const onResize = () => setWidth(document.documentElement.clientWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // 只有跨过 1800 这条线才重置右栏：在 1440 手动拉开抽屉、再把窗口拖到 1920，
  // 不该被强行关掉；反过来从 1920 缩回 1440 则必须收起来，不然 340 的抽屉会盖住半屏。
  useEffect(() => {
    if (pinned === wasPinned) return;
    setWasPinned(pinned);
    setRightOpen(pinned);
  }, [pinned, wasPinned]);

  const left: LeftLayout =
    width >= LEFT_RAIL ? (expanded ? "full" : "rail") : "hidden";

  // 1440 以上是「288 钉住 / 64 图标轨」，1024–1439 也走同一条路：点展开就是这一列变宽，
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
