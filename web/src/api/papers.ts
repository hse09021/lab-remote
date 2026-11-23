import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiUrl, get, isMockPath, send, upload } from './client'
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
      send<unknown>('PUT', `/papers/${encodeURIComponent(id)}/summary-md`, { markdown }),
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
    mutationFn: async ({ reference, save, savedId }: { reference: Reference; save: boolean; savedId?: string }) => {
      if (!isMockPath('/papers/reference', 'POST')) {
        // 실제 API — arXiv 번호가 있으면 arXiv 로, 없으면 메타만으로 vault 에 새 노트. 취소는 휴지통으로
        if (!save) return savedId ? send<unknown>('PUT', `/papers/${encodeURIComponent(savedId)}/trash`, { on: true }) : undefined
        return send<unknown>('POST', '/papers/reference', {
          title: reference.title,
          authors: reference.authors,
          year: String(reference.year ?? ''),
          venue: reference.venue,
          arxiv: reference.arxiv ?? '',
        })
      }
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

/* ── 라이브러리에 묻기 (실제 API) ─────────────────────────────────────── */

export interface AskJob {
  id: string
  state: 'running' | 'done' | 'failed'
  question: string
  answer: string
  sources: { paperId: string; label: string; why: string }[]
  error: string
}

/** 전부 mock 일 때만 목업의 예시 대화를 보여 줘요 */
export const askIsLive = () => !isMockPath('/papers/ask', 'POST')

export function useAskLibrary() {
  return useMutation({
    mutationFn: (v: { question: string; history: { role: 'user' | 'assistant'; text: string }[] }) =>
      send<AskJob>('POST', '/papers/ask', v),
  })
}

/** 답이 올 때까지 1.5초마다 물어봐요 */
export const askJobQuery = (id: string | null) =>
  queryOptions({
    queryKey: ['papers', 'ask', id],
    queryFn: () => get<AskJob>(`/papers/ask/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.state === 'running' || !q.state.data ? 1500 : false),
  })

/* ── 휴지통 · 모음 · BibTeX (lab.remote 에만 기록 — vault 는 그대로) ─────── */

export const trashQuery = () =>
  queryOptions({ queryKey: ['papers', 'trash'], queryFn: () => get<Paper[]>('/papers?trash=true') })

export const collectionsQuery = () =>
  queryOptions({
    queryKey: ['papers', 'collections'],
    queryFn: () => get<{ name: string; count: number }[]>('/papers/collections'),
  })

export function usePaperActions() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ['papers'] })
  return {
    trash: useMutation({
      mutationFn: ({ ids, on }: { ids: string[]; on: boolean }) =>
        Promise.all(ids.map((id) => send<unknown>('PUT', `/papers/${encodeURIComponent(id)}/trash`, { on }))),
      onSuccess: done,
    }),
    addCollection: useMutation({
      mutationFn: (name: string) => send<unknown>('POST', '/papers/collections', { name }),
      onSuccess: done,
    }),
    removeCollection: useMutation({
      mutationFn: (name: string) => send<unknown>('DELETE', `/papers/collections/${encodeURIComponent(name)}`),
      onSuccess: done,
    }),
    setMembers: useMutation({
      mutationFn: ({ name, ids, on }: { name: string; ids: string[]; on: boolean }) =>
        send<unknown>('POST', `/papers/collections/${encodeURIComponent(name)}/papers`, { ids, on }),
      onSuccess: done,
    }),
  }
}

/** 고른 논문의 BibTeX 글 (실제 API). mock 이면 제목만으로 만들어요 */
export async function fetchBibtex(papers: Paper[]): Promise<string> {
  if (isMockPath('/papers/bibtex')) {
    return papers.map((p) => `@article{${p.id},\n  title = {${p.title}},\n  author = {${p.authors}}\n}`).join('\n\n')
  }
  const res = await fetch(apiUrl(`/papers/bibtex?ids=${papers.map((p) => encodeURIComponent(p.id)).join(',')}`))
  if (!res.ok) throw new Error(`BibTeX 를 만들지 못했어요 (${res.status})`)
  return res.text()
}

/* ── AI 요약 (누를 때만 · vault 에 `<이름> 요약.md` 새 파일) ──────────────────── */

/** 논문 노트 본문 (요약이 없을 때 보여 줄 것) */
export const notesQuery = () =>
  queryOptions({ queryKey: ['papers', 'notes'], queryFn: () => get<Record<string, string>>('/papers/notes') })

export interface SummaryJob {
  id: string
  state: 'idle' | 'running' | 'done' | 'failed'
  error: string
}

export function useMakeSummary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => send<SummaryJob>('POST', `/papers/${encodeURIComponent(id)}/summary`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['papers'] }),
  })
}

/** 만드는 동안 3초마다 물어보고, 끝나면 목록 · 요약을 새로 받아요 */
export function useSummaryJob(id: string, enabled: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: ['papers', 'summary-job', id],
    queryFn: async () => {
      const j = await get<SummaryJob>(`/papers/${encodeURIComponent(id)}/summary`)
      if (j.state !== 'running') void qc.invalidateQueries({ queryKey: ['papers'] })
      return j
    },
    enabled,
    refetchInterval: (q) => (q.state.data?.state === 'running' || !q.state.data ? 3000 : false),
  })
}
