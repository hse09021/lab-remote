/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare global {
  // eslint-disable-next-line no-var
  var MonacoEnvironment: import('monaco-editor').Environment | undefined
}

export {}
