import { ApiError, apiBase, isMockPath } from '@/api/client'
import { sanitizePaperHtml } from '@/lib/sanitize'

const API_BASE = apiBase()

export interface LoadedPaperHtml {
  html: string
  /** 실제 arXiv HTML 이면 true. 글자 단위 하이라이트를 쓸 수 있어요 */
  isReal: boolean
}

/**
 * 논문 본문 HTML 가져오기.
 *
 * 개발 중에 web/fixtures/<id>.arxiv.html을 두면 그걸 읽고,
 * 없으면 구조만 담은 샘플 골격을 써요. 둘 다 DOMPurify를 거쳐요.
 */
export async function loadPaperHtml(paperId: string): Promise<LoadedPaperHtml> {
  if (import.meta.env.DEV) {
    try {
      const res = await fetch(`/fixtures/${encodeURIComponent(paperId)}.arxiv.html`)
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
      // fixtures가 없으면 샘플로 떨어져요
    }
  }

  const path = `/papers/${encodeURIComponent(paperId)}/html`
  if (isMockPath(path)) {
    // mock으로 돌 때만 골격을 가져와요. 실제 서버를 볼 땐 번들에 안 들어가요
    const sample = await import('@/api/mock/attn.sample.html?raw')
    return { html: sanitizePaperHtml(sample.default), isReal: false }
  }

  // 서버가 arXiv에서 받아 둔 본문 (그림 주소는 서버가 같은 출처로 바꿔 둬요)
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new ApiError(res.status, path)
  return { html: sanitizePaperHtml(await res.text()), isReal: true }
}
