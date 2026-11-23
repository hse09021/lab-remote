import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { apiUrl, isMockMode } from '@/api/client'
import type { AgentEvent, SessionDetail } from '@/api/agents'

/**
 * 서버 → 화면 실시간 이벤트(SSE) 하나를 앱 전체에서 열어 둬요.
 * 받은 이벤트로 해당 쿼리를 다시 읽거나, 채팅에는 바로 이어 붙여요.
 * 끊기면 브라우저가 알아서 다시 붙어요(서버가 retry 3초를 알려 줘요).
 */
export function useServerEvents() {
  const qc = useQueryClient()
  useEffect(() => {
    if (isMockMode() || typeof EventSource === 'undefined') return
    const es = new EventSource(apiUrl('/events'))
    // 다시 붙으면 끊긴 사이 놓친 이벤트가 있을 수 있어요 — 통째로 다시 읽어요
    es.onopen = () => qc.invalidateQueries({ queryKey: ['agents'] })
    const on = (kind: string, handle: (data: never) => void) =>
      es.addEventListener(kind, (e) => handle(JSON.parse((e as MessageEvent).data) as never))

    on('session.event', (d: { session: string; event: AgentEvent }) => appendEvent(qc, d.session, d.event))
    on('session.state', (d: { session: string }) => {
      qc.invalidateQueries({ queryKey: ['agents', 'sessions'] })
      qc.invalidateQueries({ queryKey: ['agents', 'session', d.session], refetchType: 'none' })
    })
    on('session.created', () => qc.invalidateQueries({ queryKey: ['agents', 'sessions'] }))
    const approvals = () => {
      qc.invalidateQueries({ queryKey: ['agents', 'sessions'] })
      qc.invalidateQueries({ queryKey: ['inbox'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    }
    on('approval.new', approvals)
    on('approval.done', approvals)
    on('inbox.new', () => qc.invalidateQueries({ queryKey: ['inbox'] }))
    return () => es.close()
  }, [qc])
}

function appendEvent(qc: QueryClient, sid: string, event: AgentEvent) {
  qc.setQueryData<SessionDetail>(['agents', 'session', sid], (old) =>
    old ? { ...old, events: [...old.events, event] } : old,
  )
}
