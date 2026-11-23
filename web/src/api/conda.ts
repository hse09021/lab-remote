import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/conda.py 와 짝 */

export interface CondaEnv {
  name: string
  prefix: string
  protected: boolean
  protectedReason: string
  /** 이 환경을 쓰는 실행 중인 학습 ("프로젝트 · EXP-007") */
  usedBy: string[]
}

export interface CondaPackage {
  name: string
  version: string
  source: 'conda' | 'pip'
  channel: string
  build: string
}

export interface CondaEnvDetail extends CondaEnv {
  python: string
  packages: CondaPackage[]
  /** 바꿀 수 없는 이유 (보호 · 사용 중). 바꿀 수 있으면 "" */
  lock: string
}

export interface CondaChange {
  name: string
  from: string
  to: string
  action: string
}

export interface CondaJob {
  id: string
  kind: 'change' | 'create' | 'delete'
  env: string
  tool: string
  action: string
  dry: boolean
  state: 'running' | 'done' | 'failed'
  changes: CondaChange[] | null
  error: string
  log: string
  backup: string
}

export interface PackageInput {
  name: string
  spec?: string
  extras?: string
}

/** "torch==2.7.0 peft timm>=1.0" → 패키지 목록 (서버가 다시 검사해요) */
export function parsePackages(text: string): PackageInput[] {
  return text
    .split(/[\s,]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => {
      const m = t.match(/^([A-Za-z][\w.-]*)(?:\[([\w,-]+)\])?((?:==|>=|<=|~=|!=|<|>).+)?$/)
      return m ? { name: m[1], extras: m[2] ?? '', spec: m[3] ?? '' } : { name: t }
    })
}

const enc = encodeURIComponent

export const condaEnvsQuery = () =>
  queryOptions({ queryKey: ['conda', 'envs'], queryFn: () => get<{ envs: CondaEnv[] }>('/conda/envs') })

export const condaEnvQuery = (name: string) =>
  queryOptions({ queryKey: ['conda', 'env', name], queryFn: () => get<CondaEnvDetail>(`/conda/envs/${enc(name)}`), enabled: !!name })

/** 작업이 끝날 때까지 1초마다 읽어요 */
export function useCondaJob(id: string | null) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: ['conda', 'job', id],
    queryFn: async () => {
      const job = await get<CondaJob>(`/conda/jobs/${enc(id ?? '')}`)
      if (job.state !== 'running' && !job.dry) qc.invalidateQueries({ queryKey: ['conda'] })
      return job
    },
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.state === 'running' || !q.state.data ? 1_000 : false),
  })
}

export function useCondaActions() {
  return {
    change: useMutation({
      mutationFn: (v: { env: string; tool: 'conda' | 'pip'; action: 'install' | 'update' | 'remove'; packages: PackageInput[]; dry: boolean }) =>
        send<CondaJob>('POST', `/conda/envs/${enc(v.env)}/changes`, { tool: v.tool, action: v.action, packages: v.packages, dry: v.dry }),
    }),
    create: useMutation({
      mutationFn: (v: { name: string; python: string; clone: string }) => send<CondaJob>('POST', '/conda/envs', v),
    }),
    remove: useMutation({
      mutationFn: (v: { env: string; confirm: string }) => send<CondaJob>('POST', `/conda/envs/${enc(v.env)}/delete`, { confirm: v.confirm }),
    }),
  }
}

export const condaExportHref = (name: string) => `/conda/envs/${enc(name)}/export`
