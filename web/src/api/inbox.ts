import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type { Run } from './runs'

/* server/app/inbox.py · alerts.py · dashboard.py와 짝 */

export type InboxKind = 'ask' | 'run' | 'sched' | 'pr' | 'sys'

export interface InboxItem {
  id: number
  at: string
  kind: InboxKind
  title: string
  where: string
  body: string
  project: string | null
  ref: { project?: string; run?: string; session?: string; approval?: string; schedule?: string; pr?: string }
  /** 내가 처리해야 하는 것 (답 필요 · 실패 · 끊김) */
  act: boolean
  unread: boolean
  /** "Discord 보냄" · "보내지 않음 · 조용한 시간" … */
  sent: string
}

export interface InboxPayload {
  items: InboxItem[]
  counts: Record<InboxKind, { total: number; unread: number }>
  badge: number
}

export interface NotifySettings {
  webhook: {
    set: boolean
    masked: string
    source: string
    /** 파일 권한이 600 인가 (파일이 없으면 null) */
    private: boolean | null
    last: { state: string; at: string; status: number | null; error: string | null } | null
  }
  rules: { key: string; label: string; sub: string; on: boolean }[]
  quiet: { on: boolean; start: string; end: string }
}

export interface DashboardPayload {
  now: number
  projects: number
  runs: { running: Run[]; cut: Run[]; finishedToday: Run[]; failedToday: number }
  inbox: { badge: number }
  agents: null
  prs: null
  merges: null
  self: { cpuPct: number | null; rssMb: number | null }
}

export const inboxQuery = (kind: string, unread: boolean) =>
  queryOptions({
    queryKey: ['inbox', kind, unread],
    queryFn: () => get<InboxPayload>(`/inbox?${new URLSearchParams({ ...(kind ? { kind } : {}), ...(unread ? { unread: 'true' } : {}) })}`),
    refetchInterval: 15_000,
  })

export const badgeQuery = () =>
  queryOptions({
    queryKey: ['inbox', 'badge'],
    queryFn: () => get<{ badge: number }>('/inbox/badge'),
    refetchInterval: 15_000,
    retry: false,
  })

export const notifyQuery = () =>
  queryOptions({
    queryKey: ['notify'],
    queryFn: () => get<NotifySettings>('/notify'),
  })

export const dashboardQuery = () =>
  queryOptions({
    queryKey: ['dashboard'],
    queryFn: () => get<DashboardPayload>('/dashboard'),
    refetchInterval: 5_000,
  })

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: number[] | null) => send<{ changed: number }>('POST', '/inbox/read', { ids }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['inbox'] }),
  })
}

function useNotifyMutation<V>(run: (v: V) => Promise<NotifySettings>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: (data) => qc.setQueryData(['notify'], data),
  })
}

export const useSetRules = () =>
  useNotifyMutation((rules: Record<string, boolean>) => send<NotifySettings>('PUT', '/notify/rules', { rules }))

export const useSetQuiet = () =>
  useNotifyMutation((q: { on: boolean; start: string; end: string }) => send<NotifySettings>('PUT', '/notify/quiet', q))

export const useSetWebhook = () =>
  useNotifyMutation((url: string) => send<NotifySettings>('PUT', '/notify/webhook', { url }))

export const useClearWebhook = () => useNotifyMutation(() => send<NotifySettings>('DELETE', '/notify/webhook'))

export function useTestSend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => send<{ sent: boolean; detail?: string }>('POST', '/notify/test'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notify'] }),
  })
}

/* ── Dashboard의 열린 PR · 최근 머지 (느려서 따로 · 서버가 60초 캐시) ─────── */

export interface GitFeed {
  merges: { items: { project: string; main: string; branch: string; title: string; at: number }[]; week: number; today: number }
  prs: {
    available: boolean
    reason: string
    items: { project: string; number: number; title: string; branch: string; state: string; ci: string; url: string }[]
  }
}

export const gitFeedQuery = () =>
  queryOptions({ queryKey: ['dashboard', 'git'], queryFn: () => get<GitFeed>('/dashboard/git'), refetchInterval: 60_000 })

/** 세션 카드의 git 상태 — 세션 위치의 +/− · 바뀐 파일 수 · 그 브랜치의 열린 PR */
export interface SessionCardGit {
  add: number
  del: number
  files: number
  pr: { number: number; state: string; url: string } | null
}

export const sessionCardsQuery = () =>
  queryOptions({
    queryKey: ['dashboard', 'cards'],
    queryFn: () => get<{ sessions: Record<string, SessionCardGit> }>('/dashboard/cards'),
    refetchInterval: 30_000,
  })
