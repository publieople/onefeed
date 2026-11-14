/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#14161a",
        muted: "#6b7280",
        fade: "#9aa1ab",
        line: "#e9eaec",
        paper: "#ffffff",
        wash: "#f7f8f9",
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Microsoft YaHei"', "system-ui", "-apple-system", "sans-serif"],
      },
      borderRadius: { card: "12px" },
      boxShadow: { card: "0 1px 2px rgba(20,22,26,.04)", pop: "0 12px 40px rgba(20,22,26,.10)" },
    },
  },
  plugins: [],
};
