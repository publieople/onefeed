/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" = 静态演示站：api.ts 的请求全部由 demo.ts 接管（specs/012-demo-site） */
  readonly VITE_DEMO?: string;
  /** 构建时的 base，仅用于配置文件本身；运行时读 import.meta.env.BASE_URL */
  readonly VITE_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
