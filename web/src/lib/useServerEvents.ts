import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { apiUrl, isMockMode } from '@/api/client'
import type { AgentEvent, SessionDetail } from '@/api/agents'

/** 서버가 보내는 이벤트 이름 (server/app/events.py와 짝) */
const KINDS = [
  'session.event',
  'session.state',
  'session.created',
  'approval.new',
  'approval.done',
  'inbox.new',
  'scenario.updated',
  'run.state',
] as const

const LOCK = 'labremote-events'
const CHANNEL = 'labremote-events'

/**
 * 서버 → 화면 실시간 이벤트(SSE)를 **브라우저 전체에서 하나만** 열어요.
 *
 * SSE는 끝나지 않는 연결이라, 탭마다 하나씩 열면 같은 주소로 6개까지인 브라우저 연결을
 * 차지해서 다른 요청이 끝없이 기다려요 (실측 2026-11-24: 탭 7개에서 Inbox가 멈춤).
 * 그래서 탭 하나가 Web Locks로 "연결 담당"이 되고, 받은 이벤트를 BroadcastChannel로
 * 다른 탭에 나눠 줘요. 담당 탭이 닫히면 다음 탭이 이어받아요.
 * 둘 중 하나라도 없는 브라우저에서는 예전처럼 탭마다 열어요.
 */
export function useServerEvents() {
  const qc = useQueryClient()
  useEffect(() => {
    if (isMockMode() || typeof EventSource === 'undefined') return
    const handle = (kind: string, data: unknown) => dispatch(qc, kind, data)

    const shared = typeof BroadcastChannel !== 'undefined' && typeof navigator !== 'undefined' && 'locks' in navigator
    if (!shared) return open(handle)

    const channel = new BroadcastChannel(CHANNEL)
    // 다른 탭(담당)이 나눠 준 이벤트. 보낸 탭 자신에게는 오지 않아요
    channel.onmessage = (e: MessageEvent<{ kind: string; data: unknown }>) => handle(e.data.kind, e.data.data)
    const stop = new AbortController()
    navigator.locks
      .request(LOCK, { signal: stop.signal }, () =>
        new Promise<void>((resolve) => {
          // 이 탭이 담당이 됐어요 — 연결을 열고 받은 것을 나눠 줘요
          const close = open((kind, data) => {
            handle(kind, data)
            try {
              channel.postMessage({ kind, data })
            } catch {
              // 닫힌 채널 — 탭이 닫히는 중이에요
            }
          })
          stop.signal.addEventListener('abort', () => {
            close()
            resolve()
          })
        }),
      )
      .catch(() => {
        // 기다리다 그만둠(탭을 닫거나 화면이 바뀜) — 할 일 없어요
      })
    return () => {
      stop.abort()
      channel.close()
    }
  }, [qc])
}

/** EventSource 하나를 열고 받은 이벤트를 `handle`로. 닫는 함수를 돌려줘요 */
function open(handle: (kind: string, data: unknown) => void): () => void {
  const es = new EventSource(apiUrl('/events'))
  // 다시 붙으면 끊긴 사이 놓친 이벤트가 있을 수 있어요 — 통째로 다시 읽어요
  es.onopen = () => handle('open', null)
  for (const kind of KINDS) {
    es.addEventListener(kind, (e) => handle(kind, JSON.parse((e as MessageEvent).data)))
  }
  return () => es.close()
}

function dispatch(qc: QueryClient, kind: string, data: unknown) {
  const approvals = () => {
    qc.invalidateQueries({ queryKey: ['agents', 'sessions'] })
    qc.invalidateQueries({ queryKey: ['inbox'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  switch (kind) {
    case 'open':
      qc.invalidateQueries({ queryKey: ['agents'] })
      break
    case 'session.event': {
      const d = data as { session: string; event: AgentEvent }
      appendEvent(qc, d.session, d.event)
      break
    }
    case 'session.state': {
      const d = data as { session: string }
      qc.invalidateQueries({ queryKey: ['agents', 'sessions'] })
      qc.invalidateQueries({ queryKey: ['agents', 'session', d.session], refetchType: 'none' })
      break
    }
    case 'session.created':
      qc.invalidateQueries({ queryKey: ['agents', 'sessions'] })
      break
    case 'approval.new':
    case 'approval.done':
      approvals()
      break
    case 'inbox.new':
      qc.invalidateQueries({ queryKey: ['inbox'] })
      break
    case 'run.state':
      // 실행 시작 · 끝 · 끊김 — 실행 목록 · 대시보드 · 알림을 새로
      qc.invalidateQueries({ queryKey: ['runs'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      break
    case 'scenario.updated':
      qc.invalidateQueries({ queryKey: ['scenario', (data as { project: string }).project] })
      break
  }
}

function appendEvent(qc: QueryClient, sid: string, event: AgentEvent) {
  qc.setQueryData<SessionDetail>(['agents', 'session', sid], (old) =>
    old ? { ...old, events: [...old.events, event] } : old,
  )
}
