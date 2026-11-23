import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type { ModeId } from './agents'

/* server/app/schedules.py 와 짝 */

export type ScheduleKind = 'command' | 'agent'
export type Repeat = 'once' | 'daily' | 'weekly'

export interface Schedule {
  id: number
  name: string
  kind: ScheduleKind
  project: string
  tree: string
  command: string
  env: string
  prompt: string
  mode: ModeId
  model: string
  effort: string
  /** 처음 시각 (epoch 초) */
  at: number
  repeat: Repeat
  repeatLabel: string
  enabled: boolean
  nextAt: number | null
  lastAt: number | null
  lastResult: string
  lastRef: { project?: string; run?: string; session?: string } | null
  /** GPU 가 바빠서 기다리기 시작한 시각 */
  waitingSince: number | null
}

export type ScheduleInput = Omit<Schedule, 'id' | 'repeatLabel' | 'nextAt' | 'lastAt' | 'lastResult' | 'lastRef' | 'waitingSince'>

export const schedulesQuery = () =>
  queryOptions({
    queryKey: ['schedules'],
    queryFn: () => get<{ schedules: Schedule[] }>('/schedules'),
    refetchInterval: 30_000,
  })

export function useScheduleActions() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ['schedules'] })
  return {
    create: useMutation({ mutationFn: (v: ScheduleInput) => send<Schedule>('POST', '/schedules', v), onSuccess: done }),
    update: useMutation({
      mutationFn: (v: { id: number } & Partial<ScheduleInput>) => {
        const { id, ...rest } = v
        return send<Schedule>('PUT', `/schedules/${id}`, rest)
      },
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: (id: number) => send<unknown>('DELETE', `/schedules/${id}`), onSuccess: done }),
  }
}
