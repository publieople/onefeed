import { useEffect } from "react";
import { pushScope, popScope } from "./useHotkeys";

/**
 * 把当前这一层弹窗压到键盘作用域栈顶上。
 *
 * 之前是每个弹层各自手写 pushScope/popScope，于是必然有人漏：收藏对话框就漏了，
 * 开着它按 `[` 会把左栏收起来、按 `t` 会切主题、按 `?` 会在它上面再叠一层帮助。
 * 漏一次就是一个「弹窗开着但键盘还属于页面」的 bug，所以统一走这个 hook。
 *
 * 配合 useHotkeys 里的计数栈：两层弹窗各自压一次，先关内层不会把外层的作用域掀掉。
 */
export function useModalScope(active = true): void {
  useEffect(() => {
    if (!active) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [active]);
}
