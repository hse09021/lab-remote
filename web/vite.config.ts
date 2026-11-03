import { resolve } from 'node:path'
import { existsSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import sirv from 'sirv'

const FIXTURES = resolve(import.meta.dirname, 'fixtures')

/**
 * 개발용 자산(논문 쪽 이미지, arXiv HTML)을 /fixtures 로 서빙합니다.
 * `apply: 'serve'` 이므로 프로덕션 빌드에는 들어가지 않습니다 — 배포물에
 * 샘플 논문을 넣지 않기로 했기 때문(docs/HANDOFF.md 1절).
 */
function fixturesPlugin(): Plugin {
  return {
    name: 'lab-fixtures',
    apply: 'serve',
    configureServer(server) {
      if (!existsSync(FIXTURES)) return
      server.middlewares.use('/fixtures', sirv(FIXTURES, { dev: true, etag: true }))
    },
  }
}

export default defineConfig({
  plugins: [react(), fixturesPlugin()],
  resolve: {
    alias: { '@': resolve(import.meta.dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Monaco는 /code 에서만 지연 로딩하므로 별도 청크로 떼어 둡니다.
        manualChunks(id) {
          if (id.includes('monaco-editor')) return 'monaco'
          return undefined
        },
      },
    },
  },
})
