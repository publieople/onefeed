import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 底部唤起器什么时候现身。
 *
 * 一直贴着底边会一直挡内容：读者往下翻的时候它最不该在。
 * 所以规则是：
 *   - 向下滚过 HIDE_AFTER 就把收起来；
 *   - 往回滚一点点（SHOW_ON_UP）就回来；
 *   - 指针挪进屏幕底部 EDGE 这条带，也算「想找它」，立刻出现 —— 触屏没有 hover，
 *     所以这一条只认鼠标/触控笔，手指靠滚动方向。
 * 收起只是位移 + 透明，节点还在，键盘焦点或悬停时用 hold 钉住。
 */
const HIDE_AFTER = 180;
const SHOW_ON_UP = 24;
const EDGE = 120;

export function useLauncherReveal(): { shown: boolean; hold: (v: boolean) => void } {
  const [shown, setShown] = useState(true);
  const [held, setHeld] = useState(false);
  const lastY = useRef(0);
  const raf = useRef(0);

  useEffect(() => {
    lastY.current = window.scrollY;
    const read = () => {
      const y = window.scrollY;
      const delta = y - lastY.current;
      if (Math.abs(delta) < 2) return;
      if (delta < 0 && -delta >= SHOW_ON_UP) setShown(true);
      else if (delta > 0 && delta >= SHOW_ON_UP && y > HIDE_AFTER) setShown(false);
      lastY.current = y;
    };
    const onScroll = () => {
      if (raf.current) return;
      raf.current = requestAnimationFrame(() => {
        raf.current = 0;
        read();
      });
    };
    const onPointer = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      if (e.clientY >= window.innerHeight - EDGE) setShown(true);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onPointer, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onPointer);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, []);

  const hold = useCallback((v: boolean) => setHeld(v), []);
  return { shown: shown || held, hold };
}
