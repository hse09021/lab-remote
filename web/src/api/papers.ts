import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type {
  LibraryChat,
  Paper,
  PaperSummaryMap,
  ReadStatus,
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
