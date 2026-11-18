export type Theme = "light" | "dark";

const KEY = "onefeed.theme";

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function applyTheme(next: Theme): void {
  document.documentElement.classList.toggle("dark", next === "dark");
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* 隐私模式写不了也不影响 */
  }
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", next === "dark" ? "#0f1115" : "#ffffff");
}

/** 用户选过就用用户的，没选过跟系统走。 */
export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* ignore */
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** 换肤时整页做一次 View Transition：能上就上，不能上（或用户关了动效）就退回直接换。 */
export function runThemeTransition(apply: () => void): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Document & {
    startViewTransition?: (callback: () => void) => { finished: Promise<void> };
  };
  if (reduce || typeof doc.startViewTransition !== "function") {
    apply();
    return;
  }
  const root = document.documentElement;
  // 快照期间关掉逐元素的颜色过渡：否则新快照抓到的是过渡起点色，扫过来的还是旧配色
  root.classList.add("theme-vt");
  const vt = doc.startViewTransition(apply);
  vt.finished.finally(() => root.classList.remove("theme-vt"));
}
