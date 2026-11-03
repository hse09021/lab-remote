import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type {
  LibraryChat,
  Paper,
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
 * 캐시를 바로 고쳐서 라이브러리와 리더가 같은 값을 보게 해요.
 * (리더도 같은 ['papers'] 캐시를 쓸 거예요)
 */
export function useSetReadStatus() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: ReadStatus }) =>
      send<{ id: string; status: ReadStatus }>('PATCH', `/papers/${id}`, { id, status }),

    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ['papers'] })
      const previous = qc.getQueryData<Paper[]>(['papers'])
      qc.setQueryData<Paper[]>(['papers'], (list) =>
        list?.map((p) => (p.id === id ? { ...p, status } : p)),
      )
      return { previous }
    },

    // 실패하면 되돌려요
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(['papers'], ctx.previous)
    },

    // TODO(FastAPI): 서버가 붙으면 여기서 invalidate 해 서버 값으로 맞춰요.
    // mock 단계에서는 되돌아올 서버 값이 없어 낙관적 갱신만 남겨요.
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
    mutationFn: ({ reference, save }: { reference: Reference; save: boolean }) =>
      save
        ? send<{ id: string }>('POST', '/papers', { id: refPaperId(reference) })
        : send<{ id: string }>('DELETE', `/papers/${refPaperId(reference)}`),

    onMutate: async ({ reference, save }) => {
      await qc.cancelQueries({ queryKey: ['papers'] })
      const previous = qc.getQueryData<Paper[]>(['papers'])
      const id = refPaperId(reference)

      qc.setQueryData<Paper[]>(['papers'], (list) => {
        const rest = (list ?? []).filter((p) => p.id !== id)
        if (!save) return rest
        const added: Paper = {
          id,
          title: reference.title,
          // short 가 이미 연도를 품고 있어요 ("Hochreiter & Schmidhuber, 1997")
          authors: reference.short,
          venue: `${reference.venue} ${reference.year}`,
          field: '[분야 미분류]',
          model: '[모델 미확인]',
          status: 'todo',
          source: reference.arxiv ? 'arxiv-html' : 'pdf',
          summaryState: 'running',
          access: '방금',
          path: null,
        }
        return [added, ...rest]
      })

      return { previous }
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(['papers'], ctx.previous)
    },
  })
}
