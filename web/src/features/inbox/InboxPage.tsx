import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  inboxQuery,
  notifyQuery,
  useClearWebhook,
  useMarkRead,
  useSetQuiet,
  useSetRules,
  useSetWebhook,
  useTestSend,
} from '@/api/inbox'
import type { InboxItem, InboxKind } from '@/api/inbox'
import { ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import { whenShort } from '@/lib/time'
import { sessionsQuery } from '@/api/agents'
import type { PendingApproval } from '@/api/agents'
import { QuickAllow } from '../agents/SessionLanes'
import s from './Inbox.module.css'

/** Inbox — docs/v3/mockups/Inbox.dc.html */
const KINDS: { id: '' | InboxKind; label: string }[] = [
  { id: '', label: '전체' },
  { id: 'ask', label: '답 필요' },
  { id: 'run', label: '실행' },
  { id: 'sched', label: '예약' },
  { id: 'pr', label: 'PR · 머지' },
  { id: 'sys', label: '시스템' },
]
const KIND_LABEL: Record<InboxKind, string> = { ask: '답 필요', run: '실행', sched: '예약', pr: 'PR · 머지', sys: '시스템' }

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : undefined)

export default function InboxPage() {
  const [params, setParams] = useSearchParams()
  const kind = (params.get('kind') ?? '') as '' | InboxKind
  const unread = params.get('unread') === '1'
  const list = useQuery(inboxQuery(kind, unread))
  const all = useQuery(inboxQuery('', false))
  const markRead = useMarkRead()
  const agents = useQuery(sessionsQuery())
  const pending = agents.data?.pending ?? []

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const counts = all.data?.counts

  return (
    <div className={s.page}>
      <nav aria-label="알림 종류" className={s.nav}>
        <h1 className={s.title}>Inbox</h1>
        {KINDS.map((k) => {
          const c = k.id ? counts?.[k.id] : undefined
          const total = k.id ? (c?.total ?? 0) : Object.values(counts ?? {}).reduce((n, x) => n + x.total, 0)
          const un = k.id ? (c?.unread ?? 0) : Object.values(counts ?? {}).reduce((n, x) => n + x.unread, 0)
          return (
            <button key={k.id || 'all'} type="button" aria-pressed={kind === k.id} className={s.filter} onClick={() => set('kind', k.id)}>
              <span>{k.label}</span>
              <span className={s.filterCount} data-new={un > 0}>
                {un ? `${un} 새` : total}
              </span>
            </button>
          )
        })}
        <button type="button" role="checkbox" aria-checked={unread} className={s.unreadToggle} onClick={() => set('unread', unread ? '' : '1')}>
          <span className={s.box} data-on={unread}>
            {unread ? '✓' : ''}
          </span>
          안 읽은 것만
        </button>
        <button type="button" className={s.readAll} disabled={markRead.isPending} onClick={() => markRead.mutate(null)}>
          모두 읽음으로
        </button>
      </nav>

      <main className={s.main}>
        <section aria-label="알림 목록">
          {list.isPending && <LoadingState label="알림을 불러오는 중이에요" />}
          {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
          {list.data?.items.map((it) => (
            <Item key={it.id} it={it} pending={pending.find((x) => x.id === it.ref.approval)} onRead={() => markRead.mutate([it.id])} />
          ))}
          {list.data && list.data.items.length === 0 && <div className={s.empty}>알림이 없어요.</div>}
        </section>
      </main>

      <DiscordPanel />
    </div>
  )
}

function actions(it: InboxItem): { primary?: [string, string, boolean]; secondary?: [string, string] } {
  const p = it.ref.project
  const r = it.ref.run
  if (it.kind === 'ask' && p && it.ref.session) {
    return { primary: [`/projects/${encodeURIComponent(p)}/ade?session=${encodeURIComponent(it.ref.session)}`, 'ADE에서 답하기', true], secondary: ['/dashboard', '대시보드'] }
  }
  if (it.kind === 'run' && p && r) {
    const base = `/projects/${encodeURIComponent(p)}?tab=work&run=${encodeURIComponent(r)}`
    if (it.title.endsWith('끊김')) return { primary: [`${base}&rerun=${encodeURIComponent(r)}`, '이어서 실행…', false], secondary: [base, '로그 보기'] }
    if (it.title.endsWith('실패')) return { primary: [base, '로그 보기', false], secondary: ['/settings/conda', 'conda 환경'] }
    return { secondary: [base, '로그 보기'] }
  }
  if (it.kind === 'sys') return { secondary: ['/dashboard', '자원 보기'] }
  return {}
}

function Item({ it, pending, onRead }: { it: InboxItem; pending?: PendingApproval; onRead: () => void }) {
  const a = actions(it)
  const at = new Date(it.at)
  return (
    <article className={s.item} data-unread={it.unread}>
      <span aria-hidden="true" className={s.dot} data-kind={it.unread ? it.kind : 'read'} />
      <div className={s.itemBody}>
        <div className={s.itemTop}>
          <span className={s.pill} data-kind={it.kind}>
            {KIND_LABEL[it.kind]}
          </span>
          <span className={s.itemTitle}>{it.title}</span>
          <span className={s.where}>{it.where}</span>
          <span className={s.ago}>{whenShort(at.getTime() / 1000)}</span>
        </div>
        {it.body && <p className={s.text}>{it.body}</p>}
        <div className={s.itemActions}>
          {a.primary && (
            <Link to={a.primary[0]} className={s.primary} data-strong={a.primary[2]} onClick={onRead}>
              {a.primary[1]}
            </Link>
          )}
          {a.secondary && (
            <Link to={a.secondary[0]} className={s.secondary} onClick={onRead}>
              {a.secondary[1]}
            </Link>
          )}
          {it.unread && (
            <button type="button" className={s.secondary} onClick={onRead}>
              읽음
            </button>
          )}
          {pending && <QuickAllow p={pending} via="Inbox" />}
          {it.kind === 'ask' && it.ref.approval && !pending && <span className={s.sent}>답했어요</span>}
          {it.sent && <span className={s.sent}>{it.sent}</span>}
        </div>
      </div>
    </article>
  )
}

function DiscordPanel() {
  const settings = useQuery(notifyQuery())
  const setRules = useSetRules()
  const setQuiet = useSetQuiet()
  const clear = useClearWebhook()
  const test = useTestSend()
  const [editing, setEditing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [quietOpen, setQuietOpen] = useState(false)

  if (settings.isPending) return <aside className={s.aside}><LoadingState label="Discord 설정을 불러오는 중이에요" /></aside>
  if (settings.isError) return <aside className={s.aside}><ErrorState error={settings.error} onRetry={() => settings.refetch()} /></aside>
  const d = settings.data
  const w = d.webhook

  return (
    <aside aria-label="Discord 연동" className={s.aside}>
      <section className={s.card}>
        <h2 className={s.h2}>Discord 웹훅</h2>
        <div className={s.hook} data-set={w.set}>
          {w.set ? w.masked : '아직 연결하지 않았어요'}
        </div>
        <p className={s.note}>
          웹훅 주소는 lab.remote 데이터 폴더에만 저장해요 (나만 읽기{w.private === false ? ' — ⚠ 지금 권한이 넓어요' : ''}). repo에는
          올라가지 않아요.
          {w.last && ` 마지막 전송 · ${whenShort(new Date(w.last.at).getTime() / 1000)} ${w.last.state === 'sent' ? '성공' : '실패'}`}
        </p>
        <div className={s.row}>
          <button type="button" className={s.btn} disabled={!w.set || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? '보내는 중…' : '테스트 보내기'}
          </button>
          <button type="button" className={s.btn} onClick={() => setEditing(true)}>
            {w.set ? '주소 바꾸기' : '주소 넣기'}
          </button>
          {w.set && (
            <button type="button" className={s.btnDanger} onClick={() => setConfirmClear(true)}>
              연결 끊기
            </button>
          )}
        </div>
        {test.data && (
          <div role="status" className={s.note}>
            {test.data.sent ? 'Discord로 보냈어요.' : test.data.detail}
          </div>
        )}
        {test.isError && <div role="alert" className={s.errText}>{errText(test.error)}</div>}
      </section>

      <section className={s.card}>
        <h2 className={s.h2}>Discord로 보낼 알림</h2>
        {d.rules.map((r) => (
          <button
            key={r.key}
            type="button"
            role="switch"
            aria-checked={r.on}
            className={s.rule}
            disabled={setRules.isPending}
            onClick={() => setRules.mutate({ [r.key]: !r.on })}
          >
            <span className={s.ruleText}>
              <span className={s.ruleTitle}>{r.label}</span>
              <span className={s.ruleSub}>{r.sub}</span>
            </span>
            <span aria-hidden="true" className={s.track} data-on={r.on}>
              <span className={s.knob} />
            </span>
          </button>
        ))}
        <div className={s.quiet}>
          조용한 시간{' '}
          <b>{d.quiet.on ? `${d.quiet.start} – ${d.quiet.end}` : '꺼짐'}</b>
          {d.quiet.on && ' · 이때는 답 필요와 실패만 보내요.'}{' '}
          <button type="button" className={s.link} onClick={() => setQuietOpen(true)}>
            바꾸기
          </button>
        </div>
        <p className={s.note}>예약 · PR · 머지 알림은 해당 기능이 붙는 단계(4·5단계)부터 실제로 와요.</p>
      </section>

      <WebhookDialog open={editing} onClose={() => setEditing(false)} />
      <Dialog
        open={confirmClear}
        title="Discord 연결 끊기"
        confirmLabel="끊기"
        tone="danger"
        busy={clear.isPending}
        error={errText(clear.error)}
        onClose={() => setConfirmClear(false)}
        onConfirm={() => clear.mutate(undefined, { onSuccess: () => setConfirmClear(false) })}
      >
        <span>저장한 웹훅 주소를 지워요. Inbox 알림은 계속 쌓이고 Discord로만 안 가요.</span>
      </Dialog>
      <QuietDialog key={String(quietOpen)} open={quietOpen} quiet={d.quiet} busy={setQuiet.isPending} error={errText(setQuiet.error)}
        onClose={() => setQuietOpen(false)}
        onSave={(q) => setQuiet.mutate(q, { onSuccess: () => setQuietOpen(false) })}
      />
    </aside>
  )
}

function WebhookDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const set = useSetWebhook()
  const [url, setUrl] = useState('')
  const close = () => {
    setUrl('')
    set.reset()
    onClose()
  }
  return (
    <Dialog
      open={open}
      title="Discord 웹훅 주소"
      confirmLabel="저장"
      busy={set.isPending}
      error={errText(set.error)}
      onClose={close}
      onConfirm={() => set.mutate(url, { onSuccess: close })}
    >
      <label className={ds.field}>
        Discord 채널 설정 › 연동 › 웹후크에서 복사한 주소
        {/* 비밀값이라 화면에 남기지 않아요 — 입력칸도 가려요 */}
        <input
          className={ds.input}
          type="password"
          autoComplete="off"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://discord.com/api/webhooks/…"
          autoFocus
          required
        />
      </label>
      <span>저장하면 데이터 폴더의 discord.json에 권한 600으로만 써요. 화면·로그에는 가린 주소만 보여요.</span>
    </Dialog>
  )
}

function QuietDialog({
  open,
  quiet,
  busy,
  error,
  onClose,
  onSave,
}: {
  open: boolean
  quiet: { on: boolean; start: string; end: string }
  busy: boolean
  error?: string
  onClose: () => void
  onSave: (q: { on: boolean; start: string; end: string }) => void
}) {
  const [on, setOn] = useState(quiet.on)
  const [start, setStart] = useState(quiet.start)
  const [end, setEnd] = useState(quiet.end)
  return (
    <Dialog open={open} title="조용한 시간" confirmLabel="저장" busy={busy} error={error} onClose={onClose} onConfirm={() => onSave({ on, start, end })}>
      <label className={ds.check}>
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
        <span>조용한 시간 쓰기 — 이때는 답 필요와 실패만 Discord로 보내요.</span>
      </label>
      <label className={ds.field}>
        시작
        <input className={ds.input} type="time" value={start} onChange={(e) => setStart(e.target.value)} disabled={!on} />
      </label>
      <label className={ds.field}>
        끝
        <input className={ds.input} type="time" value={end} onChange={(e) => setEnd(e.target.value)} disabled={!on} />
      </label>
    </Dialog>
  )
}
