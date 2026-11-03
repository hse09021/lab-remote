import type { PDFDocumentProxy } from 'pdfjs-dist'

/**
 * pdfjs 를 한 번만 불러와요.
 * 워커는 번들에서 가져와요 — Monaco 때처럼 CDN 으로 나가면 안 돼요.
 */
let docPromise: Promise<PDFDocumentProxy | null> | null = null
/** 정리는 로딩 작업이 맡아요 (문서에는 destroy 가 없어요) */
let task: { destroy: () => Promise<void> } | null = null

async function load(url: string): Promise<PDFDocumentProxy | null> {
  const pdfjs = await import('pdfjs-dist')
  // ?url 로 받으면 Vite 가 워커 파일을 번들에 넣고 같은 출처 주소를 줘요
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

  try {
    const loading = pdfjs.getDocument({
      url,
      /*
       * 글꼴과 CJK 문자표는 같은 출처에서 받아요 (외부 요청 0).
       * vite.config.ts 의 pdfAssetsPlugin 이 이 자리에 넣어 줘요.
       * 둘 다 쓰는 파일만 받아서, 라틴 문자 PDF 는 cmaps 를 안 받아요.
       */
      standardFontDataUrl: '/pdfjs/standard_fonts/',
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
    })
    task = loading
    return await loading.promise
  } catch {
    // 파일이 없으면 이미지 렌더러로 돌아가요
    return null
  }
}

export function loadPdf(url: string): Promise<PDFDocumentProxy | null> {
  docPromise ??= load(url)
  return docPromise
}

/** 화면을 떠날 때 정리해요 */
export function releasePdf() {
  const t = task
  docPromise = null
  task = null
  void t?.destroy().catch(() => {})
}

export type { PDFDocumentProxy }
