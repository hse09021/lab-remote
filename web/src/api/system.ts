import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/system.py와 짝 */

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
  tunnel: TunnelStatus & RemoteInfo
  autostart: {
    unit: string
    unitFile: string
    installed: boolean
    enabled: string
    active: string
    /** systemd가 다시 띄운 횟수 */
    restarts: number | null
    port: number | null
    linger: boolean | null
    /** 켜기 전 linger (lab.remote가 기억한 값) */
    lingerBefore?: boolean | null
    systemctl: boolean
    /** 이 서버가 그 서비스 안에서 도는가 */
    inside: boolean
    /** 서버 출력 보는 명령 */
    tmux: string
    installCommand: string
  }
  /** "지우기" 명령 (이 컴퓨터의 실제 경로) */
  uninstall: string[]
  gpu: GpuSummary
  host: {
    cpuPct: number | null
    memory: { totalGb?: number; usedGb?: number; pct?: number }
    disk: { freeGb?: number; totalGb?: number; pct?: number }
    load: number[] | null
  }
  changes: ChangeRow[]
  clock?: { running: boolean; lastTick: number | null; error: string; interval: number; next: { name: string; at: number; project: string } | null; waiting: string[] }
}

/** code tunnel — 읽기만 (켜는 건 사람이 `code tunnel service install`) */
export interface TunnelStatus {
  cli: string
  /** absent: CLI 없음 · off: 꺼짐 · up: 켜짐 · unknown: 못 읽음 */
  state: 'absent' | 'off' | 'up' | 'unknown'
  /** `code tunnel service install`로 설치됐나 */
  service: boolean
  loggedIn: boolean | null
  name: string
  /** vscode.dev/tunnel/<이름> */
  url: string
  detail: string
}

/** 터널로 전달한 lab.remote 주소 */
export interface RemoteInfo {
  publicUrl: string
  hosts: string[]
  envHosts: string[]
}

export const healthQuery = () =>
  queryOptions({
    queryKey: ['health'],
    queryFn: () => get<{ ok: boolean; version: string; tunnel?: TunnelStatus['state'] }>('/health'),
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

export const resourcesQuery = () =>
  queryOptions({
    queryKey: ['system', 'resources'],
    queryFn: () => get<Pick<SystemOverview, 'gpu' | 'host'>>('/system/resources'),
    // 화면을 보는 동안만 5초마다 (목업: "화면을 볼 때만 5초마다")
    refetchInterval: 5_000,
  })

/** 바깥 주소 적기 · 지우기 (빈 값이면 지워요) */
export function useSetRemote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => send<RemoteInfo>('PUT', '/system/remote', { url }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system'] }),
  })
}

/** "세션 다시 켜기" — 이 서버도 그 안이면 잠깐 끊겼다가 돌아와요 */
export function useRestartSession() {
  return useMutation({ mutationFn: () => send<{ ok: boolean }>('POST', '/system/autostart/restart') })
}

/** "자동 시작 끄기…" — 켜기는 터미널에서만 (labremote autostart install) */
export function useUninstallAutostart() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      send<{ steps: { what: string; ok: boolean; detail: string }[]; stopsSelf: boolean }>('POST', '/system/autostart/uninstall', {
        confirm: '끄기',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system'] }),
  })
}

/** 폴더 등록의 "찾아보기" — 홈 폴더 안의 하위 폴더 */
export interface DirList {
  path: string
  parent: string | null
  dirs: { name: string; path: string; git: boolean; registered: boolean }[]
}

export const dirsQuery = (path: string, hidden: boolean, enabled: boolean) =>
  queryOptions({
    queryKey: ['system', 'dirs', path, hidden],
    queryFn: () => get<DirList>(`/system/dirs?path=${encodeURIComponent(path)}${hidden ? '&hidden=true' : ''}`),
    enabled,
  })

/** 찾아보기 › 새 폴더 — 홈 폴더 안에 빈 폴더 (등록은 따로) */
export function useMakeDir() {
  return useMutation({
    mutationFn: (v: { parent: string; name: string; gitInit: boolean }) =>
      send<{ name: string; path: string; git: boolean }>('POST', '/system/dirs', v),
  })
}
