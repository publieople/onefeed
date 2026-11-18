import { useEffect, useRef } from "react";

/**
 * 键盘快捷键的唯一入口。
 *
 * 两条规则，之前没有所以到处都漏：
 * 1. **只在栈顶响应**：对话框打开时，底下的列表快捷键（j/k/o/s）必须让位，
 *    否则按 Esc 关弹窗的同时会把列表也切走。
 * 2. **输入框里吞单键**：光标在输入框里打字时按 "t" 不能切主题。
 *    带修饰键的（⌘K）照常响应。
 */

export type Scope = "global" | "list" | "dialog";

type Handler = (e: KeyboardEvent) => void;

/** 栈底永远是 global；覆盖层压在上面 */
const stack: Scope[] = ["global"];

export function pushScope(scope: Scope): void {
  if (stack[stack.length - 1] !== scope) stack.push(scope);
}

export function popScope(scope?: Scope): void {
  const top = stack[stack.length - 1];
  if (top === "global") return;
  if (scope && top !== scope) return;
  stack.pop();
}

export function topScope(): Scope {
  return stack[stack.length - 1] ?? "global";
}

let composing = false;
if (typeof window !== "undefined") {
  window.addEventListener("compositionstart", () => {
    composing = true;
  });
  window.addEventListener("compositionend", () => {
    composing = false;
  });
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return t.isContentEditable === true;
}

interface Spec {
  key: string;
  mod: boolean;
  shift: boolean;
  alt: boolean;
}

/** "mod+k" / "shift+?" / "escape" → 结构化；不认识的一律当作字面键 */
function parse(spec: string): Spec {
  const parts = spec.toLowerCase().split("+");
  const key = parts.pop() ?? "";
  return {
    key: key === "esc" ? "escape" : key,
    mod: parts.includes("mod") || parts.includes("ctrl") || parts.includes("meta") || parts.includes("cmd"),
    shift: parts.includes("shift"),
    alt: parts.includes("alt") || parts.includes("option"),
  };
}

function hit(spec: Spec, e: KeyboardEvent): boolean {
  const key = e.key.toLowerCase();
  const same =
    spec.key === key ||
    (spec.key === "space" && (key === " " || e.code === "Space")) ||
    (spec.key === "?" && key === "/" && e.shiftKey);
  if (!same) return false;
  const mod = e.metaKey || e.ctrlKey;
  if (spec.mod !== mod) return false;
  if (spec.alt !== e.altKey && spec.key !== "?") return false;
  // 「?」在多数键盘上是 shift+/，所以含 shift 的语义交给字符本身判断
  if (spec.shift !== e.shiftKey && spec.key !== "?" && spec.key !== "/") return false;
  return true;
}

/**
 * 注册一组快捷键。map 的键写法："/"、"?"、"escape"、"mod+k"、"shift+enter"。
 */
export function useHotkeys(scope: Scope, map: Record<string, Handler>, enabled = true): void {
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (composing || e.isComposing) return;
      // 全局键在列表里也要能用（"?"、"t"、"r"）；只有弹层压在最上面时才整体让位
      const top = topScope();
      if (scope === "global" ? top === "dialog" : top !== scope) return;
      const typing = isTyping(e);
      for (const [spec, fn] of Object.entries(mapRef.current)) {
        const s = parse(spec);
        if (!hit(s, e)) continue;
        // 输入框里只放行带修饰键的，以及 escape
        if (typing && !s.mod && s.key !== "escape") return;
        fn(e);
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scope, enabled]);
}
