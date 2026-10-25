/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 设为 "1" 时前端走本地 mock 引擎，不请求后端。 */
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
