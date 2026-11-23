import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type { UserAnnotation } from './mockStore'
import type { PtRect } from './types'

export type { UserAnnotation }

/** 하이라이트·주석을 만들 때 넘기는 값 */
export interface NewAnnotation {
  kind: UserAnnotation['kind']
  text: string
  source: string
  sectionId: string
  page: number
  /** HTML 보기에서 다시 그릴 자리 */
  anchor?: { blockId: string; start: number; end: number } | null
  /** PDF 보기에서 다시 그릴 자리 (pt) */
  boxes?: PtRect[] | null
}

const key = (paperId: string) => ['papers', paperId, 'annotations'] as const

/**
 * 내가 칠한 하이라이트와 내가 쓴 주석.
 * AI 하이라이트(paper-attn.json의 highlights)는 여기 들어오지 않아요 —
 * 그건 논문 데이터라 지울 수 없고 왼쪽 레전드로 켜고 끄기만 해요.
 */
export const annotationsQuery = (paperId: string) =>
  queryOptions({
    queryKey: key(paperId),
    queryFn: () => get<UserAnnotation[]>(`/papers/${encodeURIComponent(paperId)}/annotations`),
  })

/** 저장소를 고친 다음 쿼리를 무효화해요 — 화면 상태로 들고 있지 않아요 */
function useAnnotationMutation<V>(
  paperId: string,
  run: (vars: V) => Promise<unknown>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => qc.invalidateQueries({ queryKey: key(paperId) }),
  })
}

export function useAddAnnotation(paperId: string) {
  return useAnnotationMutation(paperId, (input: NewAnnotation) =>
    send<UserAnnotation>('POST', `/papers/${encodeURIComponent(paperId)}/annotations`, {
      ...input,
      paperId,
      anchor: input.anchor ?? null,
      boxes: input.boxes ?? null,
    }),
  )
}

/** 주석 글 고치기 (하이라이트는 고칠 내용이 없어요) */
export function useUpdateAnnotation(paperId: string) {
  return useAnnotationMutation(paperId, ({ id, text }: { id: string; text: string }) =>
    send<unknown>('PATCH', `/papers/${encodeURIComponent(paperId)}/annotations/${id}`, { text }),
  )
}

export function useRemoveAnnotation(paperId: string) {
  return useAnnotationMutation(paperId, (id: string) =>
    send<unknown>('DELETE', `/papers/${encodeURIComponent(paperId)}/annotations/${id}`),
  )
}

/** 되돌리기 — 지운 것을 id·만든 시각 그대로 되살려요 */
export function useRestoreAnnotation(paperId: string) {
  return useAnnotationMutation(paperId, (annotation: UserAnnotation) =>
    send<unknown>('POST', `/papers/${encodeURIComponent(paperId)}/annotations`, annotation),
  )
}
