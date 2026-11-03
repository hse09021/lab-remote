import { sanitizePaperHtml } from '@/lib/sanitize'

export interface LoadedPaperHtml {
  html: string
  /** 실제 arXiv HTML 이면 true. 글자 단위 하이라이트를 쓸 수 있어요 */
  isReal: boolean
}

/**
 * 논문 본문 HTML 가져오기.
 *
 * 개발 중에 web/fixtures/<id>.arxiv.html 을 두면 그걸 읽고,
 * 없으면 구조만 담은 샘플 골격을 써요. 둘 다 DOMPurify 를 거쳐요.
 */
export async function loadPaperHtml(paperId: string): Promise<LoadedPaperHtml> {
  if (import.meta.env.DEV) {
    try {
      const res = await fetch(`/fixtures/${paperId}.arxiv.html`)
      if (res.ok) {
        const text = await res.text()
        // 서버 설정이 어긋나 SPA 셸(index.html)이 돌아오는 일이 있어서
        // 논문처럼 생겼는지 한 번 더 봐요
        const looksLikePaper =
          text.trim().length > 200 && !text.includes('<div id="root">')
        if (looksLikePaper) {
          return { html: sanitizePaperHtml(text), isReal: true }
        }
      }
    } catch {
      // fixtures 가 없으면 샘플로 떨어져요
    }
  }

  const sample = await import('@/api/mock/attn.sample.html?raw')
  return { html: sanitizePaperHtml(sample.default), isReal: false }
}
