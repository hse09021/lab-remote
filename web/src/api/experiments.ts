import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type {
  Dashboard,
  EventEntry,
  Experiment,
  ProjectsPayload,
} from './types'

/**
 * 실험 화면이 쓰는 쿼리들.
 * 화면은 mock JSON을 직접 import하지 않고 이 헬퍼만 써요 — FastAPI로 바꿀 때
 * client.ts 한 곳만 고치면 되도록요.
 */

export const projectsQuery = () =>
  queryOptions({
    queryKey: ['projects'],
    queryFn: () => get<ProjectsPayload>('/v1/projects'),
  })

export const dashboardQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'dashboard'],
    queryFn: () => get<Dashboard>('/experiments/dashboard'),
  })

export const experimentsQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'list'],
    queryFn: () => get<Experiment[]>('/experiments'),
  })

export const eventsQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'events'],
    queryFn: () => get<EventEntry[]>('/experiments/events'),
  })

/**
 * 실험 정지 (모바일 확인 시트).
 * 큐의 상태와 결정·이벤트 기록이 같이 바뀌어요.
 */
export function useStopExperiment() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => send<unknown>('POST', `/experiments/${id}/stop`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['experiments'] }),
  })
}

/** 루프 일시정지 / 다시 시작 */
export function usePauseLoop() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (paused: boolean) => send<unknown>('PUT', '/experiments/loop', { paused }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['experiments'] }),
  })
}
