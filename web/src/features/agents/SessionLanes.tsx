import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAnswer, useCloseSession, useInterrupt } from '@/api/agents'
import { sessionCardsQuery } from '@/api/inbox'
import type { SessionCardGit } from '@/api/inbox'
import type { AgentSession, PendingApproval } from '@/api/agents'
import { ApiError } from '@/api/client'
import { agoShort, whenShort } from '@/lib/time'
import { DiffView } from './ApprovalCard'
import s from './Lanes.module.css'

/* Dashboard의 에이전트 부분 — 왼쪽 목록 · 숫자 · 답 필요/작업 중/완료 레인. */

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
  const cards = useQuery({ ...sessionCardsQuery(), enabled: sessions.length > 0 })
  const rows: [keyof typeof lanes, string, string][] = [
    ['ask', '답이 필요해요', '카드에서 펼쳐 보고 허용하거나 ADE에서 답해요'],
    ['work', '작업 중', '마지막 출력 기준'],
    ['done', '완료', '오늘 끝난 작업 · 검토하고 이어서 진행해요'],
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
            <SessionCard key={x.id} x={x} kind={k} git={cards.data?.sessions[x.id]} />
          ))}
        </div>
      ))}
    </>
  )
}

function SessionCard({ x, kind, git }: { x: AgentSession; kind: 'ask' | 'work' | 'done'; git?: SessionCardGit }) {
  const p = x.pending[0]
  const t = x.todos
  const interrupt = useInterrupt()
  const close = useCloseSession()
  return (
    <article className={s.card} data-kind={kind}>
      <div className={s.cardTop}>
        <span className={s.project}>{x.project}</span>
        <span className={s.branch}>{x.branch || x.tree}</span>
        <span className={s.muted}>Claude Code · {whenShort(x.updatedAt)}</span>
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
      {/* git 상태 — 세션 위치의 커밋 안 한 변경 · 그 브랜치의 PR */}
      {git && (git.files > 0 || git.pr) && (
        <div className={s.gitLine}>
          {git.files > 0 && (
            <>
              <span className={s.add}>+{git.add}</span>
              <span className={s.del}>−{git.del}</span>
              <span className={s.muted}>파일 {git.files}</span>
            </>
          )}
          {git.pr && (
            <a href={git.pr.url} target="_blank" rel="noreferrer" className={s.prPill}>
              PR #{git.pr.number} {git.pr.state}
            </a>
          )}
        </div>
      )}
      <div className={s.actions}>
        <Link to={adeHref(x)} className={s.primary} data-strong={kind === 'ask'}>
          {kind === 'ask' ? (p?.tool === 'AskUserQuestion' ? 'ADE에서 질문에 답하기' : 'ADE에서 답하기') : 'ADE로 가기'}
        </Link>
        {p && <QuickAllow p={p} />}
        {kind === 'work' && (
          <button type="button" className={s.secondary} disabled={interrupt.isPending} onClick={() => interrupt.mutate(x.id)}>
            중지
          </button>
        )}
        {kind === 'done' && (
          <button
            type="button"
            className={s.secondary}
            disabled={close.isPending}
            title="목록에서 숨기고 기록은 유지해요. 메시지를 보내면 다시 열려요"
            onClick={() => close.mutate({ sid: x.id, closed: true })}
          >
            세션 닫기
          </button>
        )}
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
        <span className={s.muted}>거부하거나 이유를 남기려면 ADE에서 해요.</span>
      </div>
      {answer.error ? (
        <div role="alert" className={s.err}>
          {answer.error instanceof ApiError ? answer.error.message : String(answer.error)}
        </div>
      ) : null}
    </div>
  )
}
