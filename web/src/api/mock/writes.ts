import {
  addAnnotation,
  addSavedPaper,
  removeAnnotation,
  removeSavedPaper,
  restoreAnnotation,
  setDiscrepancy,
  setPermissions,
  setReadStatus,
  setSummaryMd,
  updateAnnotation,
} from '../mockStore'
import type { UserAnnotation } from '../mockStore'
import type { Paper, Permission, PermissionMode, ReadStatus } from '../types'

/**
 * 목업 모드의 쓰기.
 * 실제 서버라면 FastAPI 가 할 일을 저장소에 반영해요.
 * 부른 쪽(뮤테이션 훅)이 끝나고 쿼리를 무효화하면 화면이 새 값을 읽어요.
 */
export function applyMockWrite(method: string, path: string, body: unknown): unknown {
  /* 읽음 상태 */
  const paper = path.match(/^\/papers\/([^/]+)$/)
  if (paper && method === 'PATCH') {
    const { status } = body as { status: ReadStatus }
    setReadStatus(paper[1], status)
    return body
  }

  /* 인용 카드 보관하기 */
  if (path === '/papers' && method === 'POST') {
    addSavedPaper(body as Paper)
    return body
  }
  if (paper && method === 'DELETE') {
    removeSavedPaper(paper[1])
    return body
  }

  /* 요약 MD 수정본 */
  const md = path.match(/^\/papers\/([^/]+)\/summary-md$/)
  if (md && method === 'PUT') {
    const { markdown } = body as { markdown: string | null }
    setSummaryMd(md[1], markdown)
    return body
  }

  /* 수치 불일치에서 고른 재현 목표 */
  const disc = path.match(/^\/papers\/([^/]+)\/discrepancy$/)
  if (disc && method === 'PUT') {
    const { target } = body as { target: string }
    setDiscrepancy(disc[1], target)
    return body
  }

  /* 내 하이라이트·주석 */
  const anns = path.match(/^\/papers\/([^/]+)\/annotations$/)
  if (anns && method === 'POST') {
    const input = body as Omit<UserAnnotation, 'id' | 'createdAt'> | UserAnnotation
    // 되돌리기는 지웠던 것을 id·만든 시각까지 그대로 되살려요
    if ('id' in input) {
      restoreAnnotation(input)
      return input
    }
    return addAnnotation({ ...input, paperId: anns[1] })
  }

  const ann = path.match(/^\/papers\/([^/]+)\/annotations\/([^/]+)$/)
  if (ann && method === 'PATCH') {
    const { text } = body as { text: string }
    updateAnnotation(ann[1], ann[2], text)
    return body
  }
  if (ann && method === 'DELETE') {
    removeAnnotation(ann[1], ann[2])
    return body
  }

  /* 권한 설정 저장 */
  if (path === '/experiments/permissions' && method === 'PUT') {
    setPermissions(body as { mode: PermissionMode; overrides: Record<string, Permission> })
    return body
  }

  // 아직 저장소에 없는 쓰기는 보낸 값을 그대로 돌려줘요 (목업 흉내)
  return body
}
