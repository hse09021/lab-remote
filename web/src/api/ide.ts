import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/api/ide.py · files.py와 짝 */

const enc = encodeURIComponent
const q = (params: Record<string, string>) => {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v)
  const text = sp.toString()
  return text ? `?${text}` : ''
}

export interface FileContent {
  path: string
  size: number
  /** 글이 아니거나 너무 크면 null */
  text: string | null
  reason?: 'too-large' | 'binary'
  mtime?: number
}

export interface SearchHit {
  path: string
  line: number
  text: string
}

export interface TerminalInfo {
  name: string
  createdAt: number
  cwd: string
  attached: boolean
}

export const fileContentQuery = (project: string, tree: string, path: string) =>
  queryOptions({
    queryKey: ['projects', project, 'content', tree, path],
    queryFn: () => get<FileContent>(`/projects/${enc(project)}/files/content${q({ tree, path })}`),
    enabled: !!path,
    staleTime: Infinity, // 열어 둔 동안은 다시 읽지 않아요 — 편집 중인 글을 덮지 않게
  })

export const searchQuery = (project: string, tree: string, text: string, caseSensitive: boolean) =>
  queryOptions({
    queryKey: ['projects', project, 'search', tree, text, caseSensitive],
    queryFn: () =>
      get<{ results: SearchHit[]; truncated: boolean; via: string }>(
        `/projects/${enc(project)}/search${q({ tree, q: text, case: caseSensitive ? 'true' : '' })}`,
      ),
    enabled: text.trim().length >= 2,
  })

export const gitCapsQuery = (project: string) =>
  queryOptions({
    queryKey: ['projects', project, 'git', 'caps'],
    queryFn: () => get<{ pr: boolean }>(`/projects/${enc(project)}/git/caps`),
    staleTime: Infinity,
  })

export const terminalsQuery = (project: string) =>
  queryOptions({
    queryKey: ['projects', project, 'terminals'],
    queryFn: () => get<{ terminals: TerminalInfo[] }>(`/projects/${enc(project)}/terminals`),
  })

export function useSaveFile(project: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { tree: string; path: string; text: string }) =>
      send<{ path: string; size: number }>('PUT', `/projects/${enc(project)}/files/content`, v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects', project, 'git'] }),
  })
}

export function useGitAction(project: string) {
  const qc = useQueryClient()
  const done = () => {
    qc.invalidateQueries({ queryKey: ['projects', project] })
    qc.invalidateQueries({ queryKey: ['projects'] })
  }
  return {
    commit: useMutation({
      mutationFn: (v: { tree: string; message: string; paths?: string[] }) =>
        send<{ sha: string; files: string[] }>('POST', `/projects/${enc(project)}/git/commit`, v),
      onSuccess: done,
    }),
    merge: useMutation({
      mutationFn: (branch: string) => send<{ main: string; sha: string }>('POST', `/projects/${enc(project)}/git/merge`, { branch }),
      onSuccess: done,
    }),
    /** 한 파일의 커밋 안 한 변경 되돌리기 (화면에서 확인을 받은 뒤) */
    discard: useMutation({
      mutationFn: (v: { tree: string; path: string }) => send<{ path: string; removed: boolean }>('POST', `/projects/${enc(project)}/git/discard`, v),
      onSuccess: (_r, v) => {
        done()
        qc.invalidateQueries({ queryKey: ['projects', project, 'origin', v.tree, v.path] })
      },
    }),
    /** PR 열기 (gh) — 브랜치가 원격에 있고 앞선 커밋이 없을 때만 (화면이 먼저 push해요) */
    pr: useMutation({
      mutationFn: (v: { tree: string; title: string; body: string }) =>
        send<{ url: string; number: string; branch: string }>('POST', `/projects/${enc(project)}/git/pr`, v),
      onSuccess: () => {
        done()
        qc.invalidateQueries({ queryKey: ['dashboard'] })
      },
    }),
  }
}

/* ── 소스 제어의 리포지토리 줄 — server/app/git/remote.py와 짝 ── */

export interface RepoBranch {
  name: string
  upstream: string
  at: number
  sha: string
}

export type RepoInfo =
  | {
      state: 'ok'
      repo: string
      branch: string
      head: string
      hasCommit: boolean
      upstream: string
      ahead: number
      behind: number
      remotes: { name: string; url: string }[]
      local: RepoBranch[]
      remote: RepoBranch[]
      gh: boolean
    }
  | { state: 'none'; reason?: string; gh: boolean; repo: string }
  | { state: 'missing' | 'refused' | 'error'; reason?: string; gh?: boolean }

export const repoInfoQuery = (project: string, tree: string) =>
  queryOptions({
    queryKey: ['projects', project, 'git', 'repo', tree],
    queryFn: () => get<RepoInfo>(`/projects/${enc(project)}/git/repo${q({ tree })}`),
    refetchInterval: 10_000,
  })

/** 브랜치 · 원격 · 동기화 · 스테이징. 원격 전송(fetch · pull · push)은 누를 때만 */
export function useRepoAction(project: string, tree: string) {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ['projects', project] })
  const post = <T,>(path: string) => (v: object = {}) => send<T>('POST', `/projects/${enc(project)}/git/${path}`, { tree, ...v })
  const m = <V extends object | void>(path: string) =>
    useMutation({ mutationFn: (v: V) => post<RepoInfo>(path)((v ?? {}) as object), onSuccess: done })
  return {
    fetch: m<void>('fetch'),
    pull: m<void>('pull'),
    push: m<void>('push'),
    sync: m<void>('sync'),
    checkout: m<{ name: string }>('checkout'),
    branch: m<{ name: string; start?: string }>('branch'),
    remote: m<{ url: string; name?: string }>('remote'),
    init: m<void>('init'),
    publish: m<{ name: string; private: boolean }>('publish'),
    stage: m<{ paths: string[] }>('stage'),
    unstage: m<{ paths: string[] }>('unstage'),
  }
}

export function useTerminalActions(project: string) {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ['projects', project, 'terminals'] })
  return {
    create: useMutation({
      mutationFn: (tree: string) => send<{ name: string; cwd: string }>('POST', `/projects/${enc(project)}/terminals`, { tree }),
      onSuccess: done,
    }),
    kill: useMutation({
      mutationFn: (name: string) => send<unknown>('DELETE', `/projects/${enc(project)}/terminals/${enc(name)}`),
      onSuccess: done,
    }),
  }
}

/** 터미널 WebSocket 주소 — 같은 호스트의 /api 아래 */
export function terminalSocketUrl(params: { project: string; name?: string; run?: string; write?: boolean; cols?: number; rows?: number }) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const sp = new URLSearchParams({ project: params.project })
  if (params.name) sp.set('name', params.name)
  if (params.run) sp.set('run', params.run)
  if (params.write) sp.set('write', 'true')
  if (params.cols) sp.set('cols', String(params.cols))
  if (params.rows) sp.set('rows', String(params.rows))
  const base = import.meta.env.VITE_API_BASE ?? '/api'
  return `${proto}//${window.location.host}${base}/terminals/ws?${sp}`
}

/** 이 파일을 마지막으로 쓰거나 고친 에이전트 세션 (IDE 편집기 위 출처 줄) */
export interface FileOrigin {
  session: string
  title: string
  at: number
  tool: string
  closed: boolean
}

export const fileOriginQuery = (project: string, tree: string, path: string) =>
  queryOptions({
    queryKey: ['projects', project, 'origin', tree, path],
    queryFn: () => get<{ origin: FileOrigin | null }>(`/projects/${enc(project)}/files/origin?tree=${encodeURIComponent(tree)}&path=${encodeURIComponent(path)}`),
    staleTime: 15_000,
  })
