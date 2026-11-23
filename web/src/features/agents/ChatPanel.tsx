import type { ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { sessionQuery, useCloseSession, useConfigure, useInterrupt, useRenameSession, useSendMessage } from '@/api/agents'
import type { AgentEvent, AgentSession } from '@/api/agents'
import { ApiError, upload } from '@/api/client'
import { ApprovalCard, DiffView } from './ApprovalCard'
import { Composer } from './Composer'
import type { ComposerSettings } from './Composer'
import { CloseIcon } from '@/components/icons'
import s from './Agents.module.css'

/**
 * 채팅 패널 — ADE 가운데와 (4단계) IDE 오른쪽이 같은 컴포넌트를 써요.
 * 도구 사용 줄 · 할 일 · 하위 에이전트 · 승인 카드 · 결과(사용량)를 그려요.
 */
/** `via` — 승인 기록에 남는 곳 (ADE 가운데 · IDE 오른쪽) */
export function ChatPanel({ session, actions, via = 'ADE' }: { session: AgentSession; actions?: ReactNode; via?: string }) {
  const detail = useQuery(sessionQuery(session.id))
  const sendMsg = useSendMessage()
  const configure = useConfigure()
  const interrupt = useInterrupt()
  const end = useRef<HTMLDivElement>(null)
  const events = detail.data?.events ?? []

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [events.length, session.pending.length])

  const settings: ComposerSettings = { mode: session.mode, model: session.model, effort: session.effort, ultracode: !!session.ultracode }
  const rename = useRenameSession()
  const close = useCloseSession()
  const [renaming, setRenaming] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const err = [sendMsg.error, configure.error, interrupt.error, rename.error, close.error].find(Boolean)

  return (
    <section aria-label="에이전트 채팅" className={s.chat}>
      <div className={s.chatHead}>
        <span className={s.chatAgent}>Claude Code</span>
        <span className={s.conn} data-on={session.connected}>
          <span aria-hidden="true" className={s.connDot} />
          {session.connected ? '연결됨' : '쉬는 중 · 보내면 이어 가요'}
        </span>
        <span className={s.spacer} />
        {session.busy || session.state === 'ask' ? (
          <button type="button" className={s.ghostBtn} disabled={interrupt.isPending} onClick={() => interrupt.mutate(session.id)}>
            중지
          </button>
        ) : null}
        {actions}
        <button
          type="button"
          className={s.chatIconBtn}
          aria-label="세션 닫기"
          disabled={close.isPending || session.busy}
          title={session.busy ? '일하는 중에는 닫을 수 없어요 — 멈춘 뒤에' : '세션 닫기 · 목록에서 빼요 (기록은 남고 메시지를 보내면 다시 열려요)'}
          onClick={() => close.mutate({ sid: session.id, closed: true })}
        >
          <CloseIcon />
        </button>
      </div>
      <div className={s.chatTitle}>
        {renaming ? (
          <form
            className={s.renameForm}
            onSubmit={(e) => {
              e.preventDefault()
              rename.mutate({ sid: session.id, title: titleDraft }, { onSuccess: () => setRenaming(false) })
            }}
          >
            <input
              className={s.renameInput}
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setRenaming(false)}
              aria-label="세션 이름"
              autoFocus
            />
            <button type="submit" className={s.ghostBtn} disabled={rename.isPending || !titleDraft.trim()}>
              저장
            </button>
          </form>
        ) : (
          <>
            <span className={s.chatTitleText}>{session.title}</span>
            <button
              type="button"
              className={s.titleBtn}
              aria-label="세션 이름 바꾸기"
              title="이름 바꾸기"
              onClick={() => {
                setTitleDraft(session.title)
                setRenaming(true)
              }}
            >
              ✎
            </button>
          </>
        )}
        <span className={s.statePill} data-state={session.state}>
          {session.state === 'ask' ? '답이 필요해요' : session.stateLabel}
        </span>
        <span className={s.chatWhere}>
          {session.project} · {session.branch || '(브랜치 없음)'} · {session.tree === '.' ? '프로젝트 루트' : session.tree}
        </span>
      </div>

      <div className={s.messages}>
        {detail.isPending && <div className={s.muted}>불러오는 중이에요…</div>}
        <EventList events={events} />
        {session.note && <div className={s.sysNote}>{session.note}</div>}
        {session.pending.map((p) => (
          <ApprovalCard key={p.id} p={p} via={via} />
        ))}
        {session.busy && session.pending.length === 0 && <div className={s.typing}>작업 중이에요…</div>}
        <div ref={end} />
      </div>

      {err && (
        <div role="alert" className={s.errBar}>
          {err instanceof ApiError ? err.message : String(err)}
        </div>
      )}
      <Composer
        settings={settings}
        onSettings={(next) => configure.mutate({ sid: session.id, ...next })}
        onSend={(text) => sendMsg.mutate({ sid: session.id, text })}
        busy={session.busy || sendMsg.isPending}
        placeholder={session.state === 'ask' ? '승인에 먼저 답해 주세요 · 답하면 이어서 해요' : undefined}
        onAttachFile={(file) =>
          upload<{ path: string; rel: string }>(
            `/agents/attachments?project=${encodeURIComponent(session.project)}&name=${encodeURIComponent(file.name)}`,
            file,
          ).then((r) => r.path)
        }
      />
    </section>
  )
}

interface ToolView {
  call: Extract<AgentEvent, { type: 'tool' }>
  result?: Extract<AgentEvent, { type: 'tool_result' }>
}

/** 이벤트 목록을 화면 덩어리로 — 도구 호출과 결과를 짝지어요 */
export function EventList({ events }: { events: AgentEvent[] }) {
  const items = useMemo(() => {
    const results = new Map<string, Extract<AgentEvent, { type: 'tool_result' }>>()
    for (const e of events) if (e.type === 'tool_result') results.set(e.toolId, e)
    const lastTodos = events.map((e, i) => (e.type === 'todos' ? i : -1)).filter((i) => i >= 0).pop()
    return events.map((e, i) => ({ e, i, result: e.type === 'tool' ? results.get(e.toolId) : undefined, latestTodos: i === lastTodos }))
  }, [events])

  return (
    <>
      {items.map(({ e, i, result, latestTodos }) => {
        switch (e.type) {
          case 'user':
            return (
              <div key={i} className={s.user}>
                {e.text}
              </div>
            )
          case 'text':
            return (
              <div key={i} className={s.assistant} data-sub={!!e.parent}>
                {e.text}
              </div>
            )
          case 'tool':
            // 할 일 도구는 줄 대신 아래 '할 일' 상자로 보여요
            if (['TodoWrite', 'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet', 'AskUserQuestion'].includes(e.name)) return null
            return <ToolRow key={i} v={{ call: e, result }} />
          case 'todos':
            return latestTodos ? <Todos key={i} items={e.items} /> : null
          case 'subagent':
            return (
              <div key={i} className={s.subagent}>
                <span className={s.toolName}>하위 에이전트</span> {e.description} · <span className={s.muted}>{e.status}</span>
              </div>
            )
          case 'approval':
            if (e.state === 'pending') return null
            if (e.state === 'answered') {
              const picked = Object.entries(e.answers ?? {}).map(([q, a]) => `${q} → ${Array.isArray(a) ? a.join(', ') : a}`)
              return (
                <div key={i} className={s.approvalDone} data-state="allowed">
                  답함 · {[...picked, e.response ? `“${e.response}”` : ''].filter(Boolean).join(' · ')}
                  {e.via ? ` · ${e.via}` : ''}
                </div>
              )
            }
            return (
              <div key={i} className={s.approvalDone} data-state={e.state}>
                {e.state === 'allowed' ? '허용함' : '거부함'} · {e.tool}
                {e.always ? ' · 이 세션에서 계속 허용' : ''}
                {e.via ? ` · ${e.via}` : ''}
                {e.reason ? ` · “${e.reason}”` : ''}
              </div>
            )
          case 'result':
            return (
              <div key={i} className={s.resultLine} data-ok={e.ok}>
                {e.ok ? '끝났어요' : '오류로 끝났어요'} · {(e.durationMs / 1000).toFixed(1)}초 · {e.turns}턴
                {e.usage ? ` · 토큰 입력 ${tokens(e.usage)} · 출력 ${e.usage.output_tokens ?? 0}` : ''}
                {e.error ? ` · ${e.error}` : ''}
              </div>
            )
          case 'system':
            return (
              <div key={i} className={s.sysNote}>
                {e.text}
              </div>
            )
          default:
            return null
        }
      })}
    </>
  )
}

const tokens = (u: Record<string, number>) =>
  (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0)

function ToolRow({ v }: { v: ToolView }) {
  const [open, setOpen] = useState(false)
  const { call, result } = v
  const showDiff = ['Edit', 'Write', 'MultiEdit'].includes(call.name) && call.input
  return (
    <div className={s.tool} data-sub={!!call.parent}>
      <button type="button" className={s.toolHead} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className={s.toolName}>{call.name}</span>
        <span className={s.toolTarget}>{call.summary}</span>
        <span className={s.toolState} data-ok={result ? result.ok : undefined}>
          {result ? (result.ok ? '완료' : '실패 · 거부') : '…'}
        </span>
      </button>
      {open && (
        <div className={s.toolBody}>
          {showDiff && call.input ? <DiffView tool={call.name} input={call.input} /> : null}
          {result?.output && <pre className={s.codeBlock}>{result.output}</pre>}
        </div>
      )}
    </div>
  )
}

function Todos({ items }: { items: { content: string; status: string }[] }) {
  const done = items.filter((t) => t.status === 'completed').length
  return (
    <div className={s.todos}>
      <div className={s.todosHead}>
        <span className={s.toolName}>할 일</span>
        <span className={s.muted}>
          {done}/{items.length}
        </span>
      </div>
      <ul className={s.todoList}>
        {items.map((t, i) => (
          <li key={i} data-status={t.status}>
            <span aria-hidden="true">{t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '▸' : '○'}</span>
            <span>{t.content}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
