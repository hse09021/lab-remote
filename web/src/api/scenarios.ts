import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/scenarios.py 와 짝 */

export interface ScenarioStep {
  name: string
  command: string
  inputs: string[]
  outputs: string[]
  env: string
  code: string[]
  note: string
  /** 그린 뒤로 바뀐 이 단계의 코드 파일 */
  changed?: string[]
}

export interface ScenarioPayload {
  scenario: {
    version: 1
    createdAt: number
    model: string
    summary: string
    steps: ScenarioStep[]
    hashes: Record<string, string>
  } | null
  /** 그린 뒤로 바뀐 파일 */
  changed?: string[]
  job: { state: 'idle' | 'running' | 'error'; error?: string; startedAt?: number }
  path?: string
  error?: string
}

const enc = encodeURIComponent

export const scenarioQuery = (project: string) =>
  queryOptions({
    queryKey: ['scenario', project],
    queryFn: () => get<ScenarioPayload>(`/projects/${enc(project)}/scenario`),
    // 그리는 동안만 자주 (끝나면 SSE scenario.updated 로도 다시 읽어요)
    refetchInterval: (q) => (q.state.data?.job.state === 'running' ? 4_000 : 60_000),
  })

export function useDrawScenario(project: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (model: string) => send<{ started: boolean }>('POST', `/projects/${enc(project)}/scenario`, { model }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scenario', project] }),
  })
}
