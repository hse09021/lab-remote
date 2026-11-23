import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/runs.py와 짝 */

export type RunState = 'running' | 'done' | 'failed' | 'stopped' | 'cut'

export interface Run {
  id: string
  project: string
  name: string
  command: string
  env: string
  /** 프로젝트 안 실행 위치 ("." 이면 루트) */
  cwd: string
  startedAt: number
  endedAt: number | null
  exitCode: number | null
  state: RunState
  stateLabel: string
  /** 끊김 등 사유 */
  reason: string
  stopRequested: boolean
  ack: boolean
  /** 터미널에서 붙는 명령 */
  attach: string
  log: string
  durationSec: number
  metrics?: RunMetrics | null
}

export interface RunMetrics {
  id: string
  file: string | null
  format?: 'wide' | 'long'
  columns?: string[]
  last?: Record<string, number | string>
  rules: string[]
}

export interface RunBrief {
  id: string
  name: string
  state: RunState
  stateLabel: string
  startedAt: number
  endedAt: number | null
  exitCode: number | null
}

export interface ProjectRuns {
  running: RunBrief[]
  last: RunBrief | null
  total: number
}

const enc = encodeURIComponent

export const runsQuery = (project: string) =>
  queryOptions({
    queryKey: ['runs', project],
    queryFn: () => get<{ runs: Run[] }>(`/projects/${enc(project)}/runs`),
    // 실행 중인 게 있으면 화면을 보는 동안 자주 다시 읽어요
    refetchInterval: (q) => (q.state.data?.runs.some((r) => r.state === 'running') ? 3_000 : 30_000),
  })

export const runLogQuery = (project: string, id: string, live: boolean) =>
  queryOptions({
    queryKey: ['runs', project, id, 'log'],
    queryFn: () => get<{ id: string; text: string; size: number; ok: boolean }>(`/projects/${enc(project)}/runs/${enc(id)}/log?lines=400`),
    refetchInterval: live ? 2_000 : false,
  })

export const runMetricsQuery = (project: string, id: string, live: boolean) =>
  queryOptions({
    queryKey: ['runs', project, id, 'metrics'],
    queryFn: () => get<RunMetrics>(`/projects/${enc(project)}/runs/${enc(id)}/metrics`),
    refetchInterval: live ? 10_000 : false,
  })

function useRunMutation<V, R = unknown>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export const useStartRun = (project: string) =>
  useRunMutation((v: { command: string; env: string; cwd: string; name: string }) =>
    send<Run>('POST', `/projects/${enc(project)}/runs`, v),
  )

export const useStopRun = () =>
  useRunMutation((v: { project: string; id: string; force: boolean }) =>
    send<Run>('POST', `/projects/${enc(v.project)}/runs/${enc(v.id)}/stop`, { force: v.force }),
  )

export const useAckRun = () =>
  useRunMutation((v: { project: string; id: string }) =>
    send<Run>('POST', `/projects/${enc(v.project)}/runs/${enc(v.id)}/ack`),
  )
