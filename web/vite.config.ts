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
/**
 * pdfjs 가 쓰는 자산(표준 글꼴·CJK 문자표)을 같은 출처로 내줘요.
 * CDN 으로 나가면 안 되니 개발·빌드 양쪽에서 /pdfjs/<이름>/ 으로 서빙해요.
 *
 * 둘 다 "필요할 때 그 파일만" 받아요 — pdfjs 가 쓰는 글꼴·문자표만 요청하고,
 * 라틴 문자 PDF 는 cmaps 를 한 건도 받지 않아요.
 */
const PDF_ASSET_DIRS = ['standard_fonts', 'cmaps'] as const

function pdfAssetsPlugin(): Plugin {
  const dirOf = (name: string) => resolve(__dirname, `node_modules/pdfjs-dist/${name}`)

  return {
    name: 'lab-pdf-assets',
    configureServer(server) {
      for (const name of PDF_ASSET_DIRS) {
        server.middlewares.use(`/pdfjs/${name}`, sirv(dirOf(name), { dev: true }))
      }
    },
    async generateBundle() {
      const { readdir, readFile } = await import('node:fs/promises')
      for (const name of PDF_ASSET_DIRS) {
        const dir = dirOf(name)
        for (const file of await readdir(dir)) {
          this.emitFile({
            type: 'asset',
            fileName: `pdfjs/${name}/${file}`,
            source: await readFile(resolve(dir, file)),
          })
        }
      }
    },
  }
}

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
  plugins: [react(), fixturesPlugin(), pdfAssetsPlugin()],
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
