import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // base 给 GitHub Pages 的项目页用（VITE_BASE=/onefeed/）；本机开发保持 "/"。
  // 前端路由的 basename 直接取 import.meta.env.BASE_URL，两边同一个来源。
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8787" } },
  build: { outDir: "dist", emptyOutDir: true },
});
