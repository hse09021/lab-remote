import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, send } from './client'

/* server/app/agents/*.py · api/agents.py 와 짝. 이름은 에이전트 공통이에요(Claude 전용 아님). */

export type ModeId = 'manual' | 'edit' | 'plan' | 'auto'
export type SessionState = 'ask' | 'working' | 'idle' | 'error'

export interface AgentModel {
  value: string
  resolvedModel?: string
  displayName: string
  description: string
  supportsEffort?: boolean
  supportedEffortLevels?: string[]
  supportsAutoMode?: boolean
}

export interface AgentInfo {
  models: AgentModel[]
  commands: { name: string; description: string; argumentHint: string }[]
  modes: { id: ModeId; label: string }[]
  version: string
  maxLive: number
  /** Ultracode — 이 Effort 를 지원하는 모델에서만 켤 수 있어요 */
  ultracode: { needsEffort: string } | null
}

export interface PendingApproval {
  id: string
  session: string
  project: string
  tool: string
  summary: string
  input: Record<string, unknown>
  title: string
  reason: string
  createdAt: number
  /** 학습이 쓰는 환경에 설치하려는 것 같을 때 경고 (막지는 않아요) */
  warning?: string
}

export type AgentEvent = { at: number } & (
  | { type: 'user'; text: string }
  | { type: 'text'; text: string; parent?: string | null }
  | { type: 'tool'; toolId: string; name: string; summary: string; input?: Record<string, unknown>; parent?: string | null }
  | { type: 'tool_result'; toolId: string; ok: boolean; output: string }
  | { type: 'todos'; items: { content: string; status: string }[] }
  | { type: 'subagent'; taskId: string; description: string; status: string; toolId?: string | null }
  | { type: 'result'; ok: boolean; durationMs: number; turns: number; costUsd?: number | null; usage?: Record<string, number> | null; error?: string }
  | {
      type: 'approval'
      approvalId: string
      state: 'pending' | 'allowed' | 'denied' | 'answered'
      tool: string
      answers?: Record<string, string | string[]>
      response?: string
      summary?: string
      input?: Record<string, unknown>
      title?: string
      reason?: string
      via?: string
      always?: boolean
    }
  | { type: 'system'; text: string }
)

export interface AgentSession {
  id: string
  kind: string
  project: string
  title: string
  /** 프로젝트 안 실행 위치 ("." = 루트) */
  tree: string
  branch: string
  mode: ModeId
  model: string
  effort: string
  ultracode?: boolean
  agentSessionId: string
  createdAt: number
  updatedAt: number
  state: SessionState
  stateLabel: string
  lastText: string
  todos: { done: number; total: number; current: string } | null
  note: string
  connected: boolean
  busy: boolean
  pending: PendingApproval[]
  /** 닫은 세션 (목록에서 빠져요 · 메시지를 보내면 다시 열려요) */
  closed?: boolean
  /** 최근 하위 에이전트 (Agents 그래프) */
  subagents?: { taskId: string; description: string; status: string; at: number }[]
}

export interface SessionDetail extends AgentSession {
  events: AgentEvent[]
}

const enc = encodeURIComponent

export const agentInfoQuery = () =>
  queryOptions({
    queryKey: ['agents', 'info'],
    queryFn: () => get<AgentInfo>('/agents/info'),
    staleTime: 10 * 60_000,
    retry: false,
  })

export const sessionsQuery = (project = '') =>
  queryOptions({
    queryKey: ['agents', 'sessions', project],
    queryFn: () =>
      get<{ sessions: AgentSession[]; pending: PendingApproval[]; live: number }>(
        `/agents/sessions${project ? `?project=${enc(project)}` : ''}`,
      ),
    refetchInterval: 30_000,
  })

export const sessionQuery = (sid: string) =>
  queryOptions({
    queryKey: ['agents', 'session', sid],
    queryFn: () => get<SessionDetail>(`/agents/sessions/${enc(sid)}`),
    enabled: !!sid,
  })

function useAgentMutation<V, R = unknown>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      qc.invalidateQueries({ queryKey: ['inbox'] })
    },
  })
}

export const useCreateSession = () =>
  useAgentMutation(
    (v: { project: string; text: string; title?: string; tree?: string; newBranch?: string; mode: ModeId; model: string; effort: string; ultracode?: boolean }) =>
      send<SessionDetail>('POST', '/agents/sessions', v),
  )

export const useSendMessage = () =>
  useAgentMutation((v: { sid: string; text: string }) => send<AgentSession>('POST', `/agents/sessions/${enc(v.sid)}/messages`, { text: v.text }))

export const useInterrupt = () =>
  useAgentMutation((sid: string) => send<AgentSession>('POST', `/agents/sessions/${enc(sid)}/interrupt`))

export const useConfigure = () =>
  useAgentMutation((v: { sid: string; mode?: ModeId; model?: string; effort?: string; ultracode?: boolean }) =>
    send<AgentSession>('PUT', `/agents/sessions/${enc(v.sid)}/config`, { mode: v.mode, model: v.model, effort: v.effort, ultracode: v.ultracode }),
  )

export const useAnswer = () =>
  useAgentMutation(
    (v: {
      id: string
      choice: 'allow' | 'allowSession' | 'deny' | 'answer'
      reason?: string
      via: string
      answers?: Record<string, string | string[]>
      response?: string
    }) =>
      send<{ id: string; state: string }>('POST', `/approvals/${enc(v.id)}`, {
        choice: v.choice,
        reason: v.reason ?? '',
        via: v.via,
        answers: v.answers,
        response: v.response ?? '',
      }),
  )

/* ── 세션 이름 바꾸기 · 닫기 ─────────────────────────────────────────── */

/** 닫은 세션만 (ADE 의 "닫은 세션") */
export const closedSessionsQuery = (enabled: boolean) =>
  queryOptions({
    queryKey: ['agents', 'sessions', 'closed'],
    queryFn: async () => {
      const all = await get<{ sessions: AgentSession[] }>('/agents/sessions?closed=true')
      return all.sessions.filter((x) => x.closed)
    },
    enabled,
  })

export const useRenameSession = () =>
  useAgentMutation((v: { sid: string; title: string }) => send<AgentSession>('PUT', `/agents/sessions/${enc(v.sid)}/title`, { title: v.title }))

/** 닫기(closed=true) · 다시 열기(false) — 기록은 지우지 않아요 */
export const useCloseSession = () =>
  useAgentMutation((v: { sid: string; closed: boolean }) => send<AgentSession>('POST', `/agents/sessions/${enc(v.sid)}/close`, { closed: v.closed }))
