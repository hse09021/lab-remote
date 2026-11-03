import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type { DesignDraft } from './types'

const key = (paperId: string) => ['papers', paperId, 'design'] as const

/** 논문 하나의 실험 설계 초안 */
export const designDraftQuery = (paperId: string) =>
  queryOptions({
    queryKey: key(paperId),
    queryFn: () => get<DesignDraft>(`/papers/${paperId}/design`),
  })

/** 직접 넣은 값 저장 (추정 필요 항목) */
export function useSaveDesignValues(paperId: string) {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (values: Record<string, string>) =>
      send<unknown>('PUT', `/papers/${paperId}/design`, { values }),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(paperId) }),
  })
}
