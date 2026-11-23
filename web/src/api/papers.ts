import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiUrl, get, send, upload } from './client'
import type {
  LibraryChat,
  Paper,
  PaperGraph,
  VaultInfo,
  PaperReaderPayload,
  PaperSummaryMap,
  ReadStatus,
  Reference,
} from './types'

export const papersQuery = () =>
  queryOptions({
    queryKey: ['papers'],
    queryFn: () => get<Paper[]>('/papers'),
  })

export const paperSummariesQuery = () =>
  queryOptions({
    queryKey: ['papers', 'summaries'],
    queryFn: () => get<PaperSummaryMap>('/papers/summaries'),
  })

/**
 * 리더 한 편의 구조·좌표. 섹션·하이라이트·참고문헌이 들어 있어요.
 * 본문(PDF·HTML)은 다음 단계에서 따로 불러와요.
 */
export const paperReaderQuery = (paperId: string) =>
  queryOptions({
    queryKey: ['papers', paperId, 'reader'],
    queryFn: () => get<PaperReaderPayload>(`/papers/${paperId}/reader`),
  })

export const libraryChatQuery = () =>
  queryOptions({
    queryKey: ['papers', 'chat'],
    queryFn: () => get<LibraryChat>('/papers/chat'),
  })

/**
 * 읽음 상태 바꾸기.
 * 목업 모드에서도 저장소(api/mockStore)를 고친 뒤 쿼리를 무효화해요 —
 * 캐시가 비워져도, 새로 고쳐도 바꾼 값이 남아요.
 */
export function useSetReadStatus() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: ReadStatus }) =>
      send<{ id: string; status: ReadStatus }>('PATCH', `/papers/${id}`, { id, status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/** 요약 MD 수정본 저장 (null 이면 수정 취소) */
export function useSaveSummaryMd() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ id, markdown }: { id: string; markdown: string | null }) =>
      send<unknown>('PUT', `/papers/${id}/summary-md`, { markdown }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers', 'summary-md'] }),
  })
}

/** 요약 MD 수정본 — 라이브러리와 리더가 같은 값을 봐요 */
export const summaryDraftsQuery = () =>
  queryOptions({
    queryKey: ['papers', 'summary-md'],
    queryFn: () => get<Record<string, string>>('/papers/summary-md'),
  })

/** 수치 불일치에서 고른 재현 목표 */
export function useChooseDiscrepancy(paperId: string) {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (target: string) =>
      send<unknown>('PUT', `/papers/${paperId}/discrepancy`, { target }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers', paperId, 'reader'] }),
  })
}

/** 참고문헌에서 만들 라이브러리 항목의 id — 다시 눌러 취소할 때 같은 값이 나와야 해요 */
export const refPaperId = (r: Pick<Reference, 'n' | 'arxiv'>) =>
  r.arxiv ? `arxiv-${r.arxiv}` : `ref-${r.n}`

/**
 * 인용 카드의 "보관하기".
 * 참고문헌을 읽을 예정 · 요약 중 상태의 논문으로 라이브러리에 넣어요.
 * 다시 누르면 취소하고 목록에서 빼요.
 * 제목·저자·학회·연도는 참고문헌 값이고, 확인 못 한 값은 자리표시로 남겨요.
 */
export function useSaveReference() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ reference, save }: { reference: Reference; save: boolean }) => {
      const id = refPaperId(reference)
      if (!save) return send<unknown>('DELETE', `/papers/${id}`)

      const added: Paper = {
        id,
        title: reference.title,
        // short 가 이미 연도를 품고 있어요 ("Hochreiter & Schmidhuber, 1997")
        authors: reference.short,
        venue: `${reference.venue} ${reference.year}`,
        // 아직 분류 전이에요 — 표에서는 "분류 대기" 칩 하나로 보여요
        field: null,
        model: null,
        status: 'todo',
        source: reference.arxiv ? 'arxiv-html' : 'pdf',
        summaryState: 'running',
        access: '방금',
        path: null,
      }
      return send<unknown>('POST', '/papers', added)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/* ── vault · 지식그래프 (8단계, 실제 API) ─────────────────────────────── */

/** vault 위치와 노트 수 */
export const vaultQuery = () =>
  queryOptions({
    queryKey: ['papers', 'vault'],
    queryFn: () => get<VaultInfo>('/papers/vault'),
  })

/** vault 위치 바꾸기 — 빈 값이면 기본(데이터 폴더의 vault/)으로 */
export function useSetVault() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (path: string) => send<VaultInfo>('PUT', '/papers/vault', { path }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/** 노드: 논문 · 프로젝트 · 내 메모. 연결: 인용 · 프로젝트에서 사용 · 내 메모 링크 */
export const paperGraphQuery = () =>
  queryOptions({
    queryKey: ['papers', 'graph'],
    queryFn: () => get<PaperGraph>('/papers/graph'),
  })

/* ── 논문 추가 (vault 에 새 파일만 · 있는 노트는 덮지 않아요) ─────────────── */

export interface AddedPaper {
  id: string
  /** false 면 이미 있던 논문이에요 */
  created: boolean
  path: string
  pdf?: boolean
}

/** arXiv 링크로 — 제목 · 저자 · 연도 · 분야 · 초록을 받아 노트를 만들고 PDF 도 받아 둬요 */
export function useAddArxiv() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => send<AddedPaper>('POST', '/papers/arxiv', { url }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/** PDF 올리기 — 파일 이름으로 노트를 만들어요 (메타는 Obsidian에서 채워요) */
export function useUploadPdf() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => upload<AddedPaper>(`/papers/pdf?name=${encodeURIComponent(file.name)}`, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/** vault 에 있는 PDF 주소 (새 탭으로 열어요) */
export const paperPdfHref = (id: string) => apiUrl(`/papers/${encodeURIComponent(id)}/pdf`)
