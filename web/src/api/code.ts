import { queryOptions } from '@tanstack/react-query'
import { get } from './client'
import type {
  CodeChatPayload,
  CodeFile,
  Commit,
  FileNode,
  PermissionsPayload,
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

/**
 * 채팅 입력창의 권한 프리셋은 권한 설정 화면과 같은 데이터를 써요.
 * 같은 queryKey라 두 화면이 캐시를 공유해요.
 */
export const permissionModesQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'permissions'],
    queryFn: () => get<PermissionsPayload>('/experiments/permissions'),
    select: (d: PermissionsPayload) => d.modes,
  })
