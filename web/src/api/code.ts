import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'
import type {
  CodeChatPayload,
  CodeFile,
  Commit,
  FileNode,
  RunPayload,
  TerminalPayload,
} from './types'

export const codeFilesQuery = () =>
  queryOptions({
    queryKey: ['code', 'files'],
    queryFn: () => get<CodeFile[]>('/code/files'),
  })

export const fileTreeQuery = () =>
  queryOptions({
    queryKey: ['code', 'tree'],
    queryFn: () => get<FileNode>('/code/tree'),
  })

export const terminalQuery = () =>
  queryOptions({
    queryKey: ['code', 'terminal'],
    queryFn: () => get<TerminalPayload>('/code/terminal'),
  })

export const commitsQuery = () =>
  queryOptions({
    queryKey: ['code', 'commits'],
    queryFn: () => get<Commit[]>('/code/commits'),
  })

export const codeChatQuery = () =>
  queryOptions({
    queryKey: ['code', 'chat'],
    queryFn: () => get<CodeChatPayload>('/code/chat'),
  })

export const runQuery = () =>
  queryOptions({
    queryKey: ['code', 'run'],
    queryFn: () => get<RunPayload>('/code/run'),
  })

/* ── 탐색기 파일 작업 ──────────────────────────────────────── */

/** 트리를 고친 뒤 다시 읽게 해요 */
function useTreeMutation<V>(run: (vars: V) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['code', 'tree'] }),
  })
}

export function useCreateNode() {
  return useTreeMutation(({ path, kind }: { path: string; kind: 'file' | 'dir' }) =>
    send<unknown>('POST', '/code/tree', { path, kind }),
  )
}

export function useRenameNode() {
  return useTreeMutation(({ path, name }: { path: string; name: string }) =>
    send<unknown>('PATCH', '/code/tree', { path, name }),
  )
}

export function useDeleteNode() {
  return useTreeMutation((path: string) => send<unknown>('DELETE', '/code/tree', { path }))
}
