import { queryOptions } from '@tanstack/react-query'
import { get } from './client'

/* server/app/system.py 와 짝 */

export interface GpuSummary {
  available: boolean
  reason: string
  /** 헤더 한 줄 — "GPU 94% · 13.1/16G" */
  label: string
  devices: { name?: string; driver?: string; utilPct?: number; memUsedMb?: number; memTotalMb?: number; tempC?: number }[]
  driver: { mismatch?: boolean; kernel?: string; userland?: string; rebootPending?: boolean; reason?: string }
}

export interface ChangeRow {
  what: string
  where: string
  /** null 이면 모름 (linger) */
  present: boolean | null
  /** 언제 생기는지 (파일 시각은 생긴 때가 아니라서 글로 적어요) */
  when: string
  undo: string
  project?: string
}

export interface SystemOverview {
  server: {
    version: string
    pid: number
    host: string
    port: number | null
    startedAt: number
    uptimeSec: number
    nice: number | null
    python: string
    dataDir: string
    hostname: string
  }
  tunnel: { state: 'unknown' | 'up' | 'down'; note?: string }
  autostart: {
    unit: string
    unitFile: string
    installed: boolean
    enabled: string
    active: string
    linger: boolean | null
    systemctl: boolean
  }
  gpu: GpuSummary
  host: {
    cpuPct: number | null
    memory: { totalGb?: number; usedGb?: number; pct?: number }
    disk: { freeGb?: number; totalGb?: number; pct?: number }
    load: number[] | null
  }
  changes: ChangeRow[]
}

export const healthQuery = () =>
  queryOptions({
    queryKey: ['health'],
    queryFn: () => get<{ ok: boolean; version: string }>('/health'),
    // 헤더의 연결 점 — 화면을 보는 동안만 (백그라운드 탭에서는 멈춰요)
    refetchInterval: 15_000,
    retry: false,
  })

export const gpuQuery = () =>
  queryOptions({
    queryKey: ['system', 'gpu'],
    queryFn: () => get<GpuSummary>('/system/gpu'),
    refetchInterval: 15_000,
    retry: false,
  })

export const systemQuery = () =>
  queryOptions({
    queryKey: ['system'],
    queryFn: () => get<SystemOverview>('/system'),
    refetchInterval: 10_000,
  })
