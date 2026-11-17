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
