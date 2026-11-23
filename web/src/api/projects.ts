import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send, upload } from './client'

/* ── 타입 (server/app/api/projects.py · files.py · git.py 와 짝) ─────────── */

export type GitSummary =
  | { state: 'ok'; branch: string; head: string; changed: number; ahead: number; behind: number }
  | { state: 'none' | 'missing' | 'refused' | 'error'; reason?: string }

export interface ProjectSettings {
  version: 1
  condaEnv: string
  commands: string[]
  metricGlobs: string[]
  share: boolean
}

export interface ProjectRow {
  name: string
  root: string
  /** 홈을 ~ 로 줄인 경로 */
  path: string
  exists: boolean
  pinned: boolean
  /** 초 (epoch) */
  activityAt: number | null
  git: GitSummary
}

export interface ProjectDetail extends ProjectRow {
  settings: ProjectSettings
  labremote: boolean
}

export interface FileEntry {
  name: string
  /** 기준 폴더 기준 상대 경로 */
  path: string
  kind: 'file' | 'dir'
  link: boolean
  /** 프로젝트 밖을 가리키는 링크 — 열 수 없어요 */
  outside: boolean
  size: number | null
  mtime: number
  /** 수정 · 새 파일 · gitignore · 삭제 · 충돌 … 없으면 "" */
  git: string
}

export interface DirListing {
  path: string
  entries: FileEntry[]
  truncated: boolean
}

export interface Worktree {
  path: string
  /** 프로젝트 안이면 상대 경로, 밖이면 null */
  rel: string | null
  branch: string
  head: string
  primary: boolean
  detached: boolean
  prunable: boolean
  /** main 에 합쳐짐 — 정리 대상으로 표시만 해요 */
  merged: boolean
  ahead: number | null
  changed: number | null
}

export type WorktreeList =
  | { state: 'ok'; main: string; worktrees: Worktree[] }
  | { state: 'none' | 'missing' | 'refused' | 'error'; reason?: string }

/* ── 읽기 ─────────────────────────────────────────────────────────────── */

const q = (params: Record<string, string>) => {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v)
  const text = sp.toString()
  return text ? `?${text}` : ''
}

const enc = encodeURIComponent

export const projectsQuery = () =>
  queryOptions({
    queryKey: ['projects'],
    queryFn: () => get<{ projects: ProjectRow[] }>('/projects'),
  })

export const projectQuery = (name: string) =>
  queryOptions({
    queryKey: ['projects', name],
    queryFn: () => get<ProjectDetail>(`/projects/${enc(name)}`),
  })

export const dirQuery = (name: string, tree: string, path: string) =>
  queryOptions({
    queryKey: ['projects', name, 'files', tree, path],
    queryFn: () => get<DirListing>(`/projects/${enc(name)}/files${q({ tree, path })}`),
  })

export const worktreesQuery = (name: string) =>
  queryOptions({
    queryKey: ['projects', name, 'worktrees'],
    queryFn: () => get<WorktreeList>(`/projects/${enc(name)}/git/worktrees`),
  })

export const downloadHref = (name: string, tree: string, path: string) =>
  `/projects/${enc(name)}/files/download${q({ tree, path })}`

/* ── 쓰기 ─────────────────────────────────────────────────────────────── */

function useProjectMutation<V, R = unknown>(run: (vars: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export const useRegisterProject = () =>
  useProjectMutation((v: { path: string; name: string }) => send<ProjectDetail>('POST', '/projects', v))

export const useUnregisterProject = () =>
  useProjectMutation((v: { name: string; removeLabremote: boolean }) =>
    send<unknown>(
      'DELETE',
      `/projects/${enc(v.name)}${v.removeLabremote ? '?removeLabremote=true' : ''}`,
    ),
  )

export const usePinProject = () =>
  useProjectMutation((v: { name: string; pinned: boolean }) =>
    send<unknown>('PUT', `/projects/${enc(v.name)}/pin`, { pinned: v.pinned }),
  )

export const useSaveSettings = (name: string) =>
  useProjectMutation((v: Omit<ProjectSettings, 'version'>) =>
    send<ProjectSettings>('PUT', `/projects/${enc(name)}/settings`, v),
  )

export const useMakeEntry = (name: string) =>
  useProjectMutation((v: { tree: string; path: string; kind: 'file' | 'dir' }) =>
    send<unknown>('POST', `/projects/${enc(name)}/files`, v),
  )

export const useMoveEntry = (name: string) =>
  useProjectMutation((v: { tree: string; from: string; to: string }) =>
    send<unknown>('POST', `/projects/${enc(name)}/files/move`, v),
  )

export const useDeleteEntry = (name: string) =>
  useProjectMutation((v: { tree: string; path: string; confirm: string }) =>
    send<unknown>('POST', `/projects/${enc(name)}/files/delete`, v),
  )

export const useUpload = (name: string) =>
  useProjectMutation((v: { tree: string; dir: string; files: File[] }) =>
    Promise.all(
      v.files.map((f) =>
        upload<unknown>(
          `/projects/${enc(name)}/files/upload${q({ tree: v.tree, path: v.dir ? `${v.dir}/${f.name}` : f.name })}`,
          f,
        ),
      ),
    ),
  )
