import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAnswer } from '@/api/agents'
import type { AgentSession, PendingApproval } from '@/api/agents'
import { ApiError } from '@/api/client'
import { agoShort } from '@/lib/time'
import { DiffView } from './ApprovalCard'
import s from './Lanes.module.css'

/* Dashboard의 에이전트 부분 — 왼쪽 목록 · 숫자 · 답 필요/작업 중/끝남 레인. */

export const adeHref = (x: { project: string; id: string }) =>
  `/projects/${encodeURIComponent(x.project)}/ade?session=${encodeURIComponent(x.id)}`

const DAY = 24 * 3600

export function laneOf(sessions: AgentSession[], now = Date.now() / 1000) {
  return {
    ask: sessions.filter((x) => x.state === 'ask' || x.pending.length > 0),
    work: sessions.filter((x) => x.state === 'working' && x.pending.length === 0),
    done: sessions.filter((x) => x.state === 'idle' && x.pending.length === 0 && now - x.updatedAt < DAY),
  }
}

export function AgentAside({ sessions }: { sessions: AgentSession[] }) {
  const byProject = new Map<string, AgentSession[]>()
  for (const x of sessions) byProject.set(x.project, [...(byProject.get(x.project) ?? []), x])
  return (
    <div className={s.aside}>
      {sessions.length === 0 && <div className={s.muted}>세션이 없어요. ADE에서 시작해요.</div>}
      {[...byProject.entries()].map(([p, list]) => (
        <div key={p}>
          <div className={s.asideProject}>{p}</div>
          {list.slice(0, 8).map((x) => (
            <Link key={x.id} to={adeHref(x)} className={s.asideItem}>
              <span aria-hidden="true" className={s.dot} data-state={x.pending.length ? 'ask' : x.state} />
              <span className={s.asideTitle}>{x.title}</span>
              <span className={s.muted}>{agoShort(x.updatedAt)}</span>
            </Link>
          ))}
        </div>
      ))}
    </div>
  )
}

export function Lanes({ sessions }: { sessions: AgentSession[] }) {
  const lanes = laneOf(sessions)
  const rows: [keyof typeof lanes, string, string][] = [
    ['ask', '답이 필요해요', '카드에서 펼쳐 보고 허용하거나 ADE에서 답해요'],
    ['work', '작업 중', '마지막 출력 기준'],
    ['done', '끝남', '오늘 끝난 차례 · 검토하고 이어 가요'],
  ]
  return (
    <>
      {rows.map(([k, name, hint]) => (
        <div key={k} className={s.lane}>
          <div className={s.laneHead}>
            <span aria-hidden="true" className={s.dot} data-state={k === 'ask' ? 'ask' : k === 'work' ? 'working' : 'idle'} />
            <h2 className={s.h2}>{name}</h2>
            <span className={s.count}>{lanes[k].length}</span>
            <span className={s.hint}>{hint}</span>
          </div>
          {lanes[k].length === 0 && <div className={s.empty}>없어요.</div>}
          {lanes[k].map((x) => (
            <SessionCard key={x.id} x={x} kind={k} />
          ))}
        </div>
      ))}
    </>
  )
}

function SessionCard({ x, kind }: { x: AgentSession; kind: 'ask' | 'work' | 'done' }) {
  const p = x.pending[0]
  const t = x.todos
  return (
    <article className={s.card} data-kind={kind}>
      <div className={s.cardTop}>
        <span className={s.project}>{x.project}</span>
        <span className={s.branch}>{x.branch || x.tree}</span>
        <span className={s.muted}>Claude Code · {agoShort(x.updatedAt)} 전</span>
      </div>
      <h3 className={s.title}>{x.title}</h3>
      {x.lastText && <p className={s.note}>{x.lastText}</p>}
      {p && (
        <div className={s.askText}>
          {p.tool} · {p.summary}
        </div>
      )}
      {t && t.total > 0 && (
        <div className={s.todo}>
          <span className={s.muted}>할 일</span>
          <span className={s.mono}>
            {t.done}/{t.total}
          </span>
          <span className={s.todoNow}>{t.current ? `지금: ${t.current}` : t.done === t.total ? '완료' : ''}</span>
          <div className={s.track}>
            <div className={s.bar} data-kind={kind} style={{ width: `${Math.round((100 * t.done) / t.total)}%` }} />
          </div>
        </div>
      )}
      <div className={s.actions}>
        <Link to={adeHref(x)} className={s.primary} data-strong={kind === 'ask'}>
          {kind === 'ask' ? (p?.tool === 'AskUserQuestion' ? 'ADE에서 질문에 답하기' : 'ADE에서 답하기') : 'ADE로 가기'}
        </Link>
        {p && <QuickAllow p={p} />}
      </div>
    </article>
  )
}

/** "보고 허용" — 펼쳐서 diff 요약이나 명령을 본 다음에만 허용이 눌려요 (사람이 고른 방식, 2026-11-23) */
export function QuickAllow({ p, via = 'Dashboard' }: { p: PendingApproval; via?: string }) {
  const [open, setOpen] = useState(false)
  const answer = useAnswer()
  // 질문은 보기를 골라야 해서 "보고 허용"이 없어요 — ADE의 질문 카드에서 답해요
  if (p.tool === 'AskUserQuestion') return null
  if (!open) {
    return (
      <button type="button" className={s.secondary} onClick={() => setOpen(true)}>
        보고 허용…
      </button>
    )
  }
  return (
    <div className={s.quick}>
      {p.warning && <div className={s.warn}>⚠ {p.warning}</div>}
      <DiffView tool={p.tool} input={p.input} />
      <div className={s.quickActions}>
        <button type="button" className={s.allow} disabled={answer.isPending} onClick={() => answer.mutate({ id: p.id, choice: 'allow', via })}>
          허용
        </button>
        <button type="button" className={s.secondary} onClick={() => setOpen(false)}>
          접기
        </button>
        <span className={s.muted}>거부 · 이유 적기는 ADE에서 해요.</span>
      </div>
      {answer.error ? (
        <div role="alert" className={s.err}>
          {answer.error instanceof ApiError ? answer.error.message : String(answer.error)}
        </div>
      ) : null}
    </div>
  )
}
