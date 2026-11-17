/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // 颜色全部走 CSS 变量，亮/暗两套值在 theme.css 里切换
      colors: {
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        fade: "rgb(var(--c-fade) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        paper: "rgb(var(--c-paper) / <alpha-value>)",
        wash: "rgb(var(--c-wash) / <alpha-value>)",
        solid: "rgb(var(--c-solid) / <alpha-value>)",
        "solid-fg": "rgb(var(--c-solid-fg) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Microsoft YaHei"', "system-ui", "-apple-system", "sans-serif"],
      },
      borderRadius: { card: "12px" },
      boxShadow: { card: "var(--shadow-card)", pop: "var(--shadow-pop)" },
    },
  },
  plugins: [],
};
