import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { schedulesQuery, useScheduleActions } from '@/api/schedules'
import type { Schedule } from '@/api/schedules'
import type { Run } from '@/api/runs'
import { ApiError } from '@/api/client'
import { Dialog, ErrorState, LoadingState } from '@/components'
import { ScheduleDialog } from './ScheduleDialog'
import s from './Schedule.module.css'

/** Dashboard › Schedule — 24시간 띠 + 예약 표 + 규칙 (목업 MissionControl) */

const HOUR = 3600
/** 띠는 오늘 08:00 → 내일 08:00 (지금이 08시 전이면 어제 08:00부터) */
function bandStart(now: Date) {
  const d = new Date(now)
  d.setMinutes(0, 0, 0)
  if (d.getHours() < 8) d.setDate(d.getDate() - 1)
  d.setHours(8)
  return d.getTime() / 1000
}

const fmtTime = (sec: number) => new Date(sec * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })

function fmtNext(sec: number | null) {
  if (!sec) return '—'
  const d = new Date(sec * 1000)
  const today = new Date()
  const tomorrow = new Date()
  tomorrow.setDate(today.getDate() + 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, today)) return `오늘 ${fmtTime(sec)}`
  if (same(d, tomorrow)) return `내일 ${fmtTime(sec)}`
  return `${d.getMonth() + 1}/${d.getDate()} (${'일월화수목금토'[d.getDay()]}) ${fmtTime(sec)}`
}

export function ScheduleView({ running }: { running: Run[] }) {
  const list = useQuery(schedulesQuery())
  const { update, remove } = useScheduleActions()
  const [dialog, setDialog] = useState<{ open: boolean; edit?: Schedule }>({ open: false })
  const [deleting, setDeleting] = useState<Schedule | null>(null)
  const now = new Date()
  const start = bandStart(now)
  const end = start + 24 * HOUR
  const pct = (sec: number) => Math.max(0, Math.min(100, ((sec - start) / (end - start)) * 100))
  const items = list.data?.schedules ?? []
  const marks = items.filter((x) => x.enabled && x.nextAt && x.nextAt >= start && x.nextAt <= end)
  const later = items.filter((x) => x.enabled && x.nextAt && x.nextAt > end).sort((a, b) => (a.nextAt ?? 0) - (b.nextAt ?? 0))[0]
  const err = update.error ?? remove.error

  return (
    <section aria-label="예약" className={s.wrap}>
      <div className={s.head}>
        <h2 className={s.h2}>
          예약 <span className={s.count}>{items.length}</span>
        </h2>
        <span className={s.muted}>IDE 실행 탭의 "예약 실행…" 또는 여기에서 만들 수 있어요</span>
        <button type="button" className={s.primary} onClick={() => setDialog({ open: true })}>
          + 예약 만들기
        </button>
      </div>

      <div className={s.band} aria-label="오늘 08:00 → 내일 08:00">
        <div className={s.bandTitle}>
          <span>오늘 08:00 → 내일 08:00</span>
          <span className={s.muted}>지금 {fmtTime(now.getTime() / 1000)}</span>
        </div>
        <div className={s.track}>
          {running.map((r) => (
            <Link
              key={`${r.project}/${r.id}`}
              to={`/projects/${encodeURIComponent(r.project)}?tab=work&run=${r.id}`}
              className={s.runBar}
              style={{ left: `${pct(r.startedAt)}%`, width: `${Math.max(1, pct(now.getTime() / 1000) - pct(r.startedAt))}%` }}
              title={`${r.project} · ${r.name || r.id} 실행 중`}
            >
              {r.name || r.id}
            </Link>
          ))}
          <span className={s.nowLine} style={{ left: `${pct(now.getTime() / 1000)}%` }} aria-hidden="true" />
          {marks.map((x) => (
            <span key={x.id} className={s.mark} style={{ left: `${pct(x.nextAt as number)}%` }} title={`${x.name} ${fmtTime(x.nextAt as number)}`}>
              <span className={s.pin} data-kind={x.kind} />
              {x.name} {fmtTime(x.nextAt as number)}
            </span>
          ))}
          {later && (
            <span className={s.later}>
              {fmtNext(later.nextAt)} {later.name} →
            </span>
          )}
        </div>
        <div className={s.ticks} aria-hidden="true">
          {[8, 11, 14, 17, 20, 23, 2, 5, 8].map((h, i) => (
            <span key={i} style={{ left: `${(i / 8) * 100}%` }}>
              {String(h).padStart(2, '0')}:00
            </span>
          ))}
        </div>
      </div>

      {list.isPending && <LoadingState label="예약을 불러오는 중이에요" />}
      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.isSuccess && (
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>이름</th>
                <th>내용</th>
                <th>다음 실행</th>
                <th>반복</th>
                <th>위치</th>
                <th>마지막 결과</th>
                <th>활성</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <td colSpan={8} className={s.empty}>
                    예약이 없어요.
                  </td>
                </tr>
              )}
              {items.map((x) => (
                <tr key={x.id} data-off={!x.enabled}>
                  <td className={s.name}>{x.name}</td>
                  <td>
                    <span className={s.kind} data-kind={x.kind}>
                      {x.kind === 'command' ? '명령' : '에이전트'}
                    </span>{' '}
                    <span className={s.what}>{x.kind === 'command' ? x.command : '세션을 열고 요청 보내기'}</span>
                  </td>
                  <td>
                    {x.waitingSince ? <span className={s.waiting}>GPU 대기 중</span> : fmtNext(x.nextAt)}
                  </td>
                  <td>{x.repeatLabel}</td>
                  <td className={s.mono}>
                    {x.project} · {x.tree || '루트'}
                  </td>
                  <td className={s.muted}>
                    {x.lastRef?.run ? (
                      <Link to={`/projects/${encodeURIComponent(x.lastRef.project ?? x.project)}?tab=work&run=${x.lastRef.run}`}>{x.lastResult}</Link>
                    ) : x.lastRef?.session ? (
                      <Link to={`/projects/${encodeURIComponent(x.project)}/ade?session=${x.lastRef.session}`}>{x.lastResult}</Link>
                    ) : (
                      x.lastResult || '—'
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={x.enabled}
                      aria-label={`${x.name} 활성화`}
                      className={s.switch}
                      disabled={update.isPending || (!x.enabled && x.repeat === 'once' && !x.nextAt)}
                      title={!x.enabled && x.repeat === 'once' && !x.nextAt ? '이미 지난 일회성 예약이에요. 수정을 눌러 시각을 다시 설정해 주세요.' : undefined}
                      onClick={() => update.mutate({ id: x.id, enabled: !x.enabled })}
                    >
                      <span className={s.knob} />
                    </button>
                  </td>
                  <td className={s.actions}>
                    <button type="button" className={s.link} onClick={() => setDialog({ open: true, edit: x })}>
                      수정
                    </button>
                    <button type="button" className={s.linkDanger} onClick={() => setDeleting(x)}>
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {err && <div className={s.err}>{err instanceof ApiError ? err.message : String(err)}</div>}

      <ul className={s.rules}>
        <li>예약 시각에 다른 학습이 GPU를 사용 중이면 끝날 때까지 기다렸다가 시작해요. 대기를 시작할 때 알려 줘요.</li>
        <li>"이전 실행이 끝나면 시작" 같은 연쇄 예약은 지원하지 않아요. 예약은 시각으로만 설정해요.</li>
        <li>에이전트 예약은 예약 시각에 세션을 열고 요청만 보내요. 승인이 필요하면 승인할 때까지 기다려요.</li>
        <li>lab.remote 서버가 시각을 확인해 실행하고, cron이나 systemd 타이머는 만들지 않아요. 서버가 중지된 동안 지나간 예약은 나중에 몰아서 실행하지 않아요.</li>
      </ul>

      <ScheduleDialog key={dialog.edit?.id ?? (dialog.open ? 'new' : 'closed')} open={dialog.open} edit={dialog.edit} onClose={() => setDialog({ open: false })} />
      <Dialog
        open={deleting !== null}
        title="예약을 삭제할까요?"
        confirmLabel="삭제"
        tone="danger"
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
      >
        <span>&lsquo;{deleting?.name}&rsquo; 예약을 삭제해도 이미 시작된 실행이나 세션에는 영향이 없어요.</span>
      </Dialog>
    </section>
  )
}
