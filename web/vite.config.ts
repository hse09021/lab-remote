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
      const serve = existsSync(FIXTURES)
        ? sirv(FIXTURES, { dev: true, etag: true })
        : null
      server.middlewares.use('/fixtures', (req, res) => {
        const done = () => {
          // 없는 파일은 404로 끝내요. 그냥 next() 하면 SPA 폴백이
          // index.html 을 200으로 돌려줘서 호출한 쪽이 속아요.
          res.statusCode = 404
          res.end('fixture not found')
        }
        if (!serve) return done()
        serve(req, res, done)
      })
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
    /*
     * Monaco를 manualChunks로 따로 떼면 진입 HTML에 modulepreload가 붙어서
     * 모든 화면이 3.8MB를 미리 받아요. 그냥 두면 /code 의 동적 import 그래프
     * 안에 들어가 그 화면에 들어갈 때만 받아요.
     */
    chunkSizeWarningLimit: 4096,
  },
})
