import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { sessionsQuery } from '@/api/agents'
import { useQuery } from '@tanstack/react-query'
import { runLogQuery, runMetricsQuery, runsQuery, useStartRun, useStopRun } from '@/api/runs'
import type { Run } from '@/api/runs'
import type { ProjectDetail, WorktreeList } from '@/api/projects'
import { ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import { copyText } from '@/lib/clipboard'
import { duration, whenShort } from '@/lib/time'
import { ScheduleDialog } from '../schedule/ScheduleDialog'
import s from './Projects.module.css'

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : undefined)

export function RunStatePill({ run }: { run: Pick<Run, 'state' | 'stateLabel'> }) {
  return (
    <span className={s.statePill} data-state={run.state}>
      {run.stateLabel}
    </span>
  )
}

export function RunsTab({ project, trees }: { project: ProjectDetail; trees?: WorktreeList }) {
  const [params, setParams] = useSearchParams()
  const list = useQuery(runsQuery(project.name))
  const sessions = useQuery(sessionsQuery(project.name))
  const selected = params.get('run') ?? ''
  const rerunId = params.get('rerun') ?? ''
  const [dialog, setDialog] = useState<{ open: boolean; from?: Run }>({ open: false })
  const [stopping, setStopping] = useState<Run | null>(null)

  const runs = list.data?.runs ?? []

  // 대시보드의 "이어서 실행…"에서 왔으면 그 실행으로 창을 채워요
  useEffect(() => {
    if (!rerunId || !list.data) return
    const from = list.data.runs.find((r) => r.id === rerunId)
    setDialog({ open: true, from })
    const next = new URLSearchParams(params)
    next.delete('rerun')
    setParams(next, { replace: true })
  }, [rerunId, list.data, params, setParams])

  const pick = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('tab', 'work')
    if (id) next.set('run', id)
    else next.delete('run')
    setParams(next, { replace: true })
  }
  const current = runs.find((r) => r.id === selected)

  return (
    <div className={s.workWrap}>
      <div className={s.workGrid}>
        <section aria-label="세션" className={s.workCard}>
          <div className={s.cardHead}>
            <h2 className={s.h2}>세션</h2>
            <Link to={`/projects/${encodeURIComponent(project.name)}/ade?new=1`} className={s.actBtnPlain}>
              새 세션
            </Link>
          </div>
          {(sessions.data?.sessions ?? []).length === 0 && <div className={s.muted}>세션이 없어요.</div>}
          {(sessions.data?.sessions ?? []).slice(0, 12).map((x) => (
            <Link key={x.id} to={`/projects/${encodeURIComponent(project.name)}/ade?session=${x.id}`} className={s.sessionRow}>
              <span aria-hidden="true" className={s.itemDot} data-tone={x.pending.length ? 'ask' : x.state === 'working' ? 'work' : 'idle'} />
              <span className={s.sessionTitle}>{x.title}</span>
              <span className={s.runId}>{x.branch || x.tree}</span>
              <span className={s.statePill} data-state={x.pending.length ? 'cut' : x.state === 'working' ? 'running' : 'done'}>
                {x.pending.length ? '답 필요' : x.stateLabel}
              </span>
            </Link>
          ))}
        </section>
        <section aria-label="실행" className={`${s.workCard} ${s.runsCard}`}>
          <div className={s.cardHead}>
            <h2 className={s.h2}>실행</h2>
            <button type="button" className={s.primaryBtn} onClick={() => setDialog({ open: true })}>
              새 실행
            </button>
          </div>
          {list.isPending && <LoadingState label="실행 기록을 불러오는 중이에요" />}
          {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
          {list.isSuccess && runs.length === 0 && <div className={s.muted}>실행 기록이 없어요.</div>}
          {runs.map((r) => (
            <div key={r.id} className={s.runRow} data-selected={r.id === selected}>
              <button type="button" className={s.runMain} onClick={() => pick(r.id === selected ? '' : r.id)}>
                <span className={s.runId}>{r.name ? `${r.id} · ${r.name}` : r.id}</span>
                <RunStatePill run={r} />
                <span className={s.runCmd} title={r.command}>
                  {r.command}
                </span>
                <span className={s.runMeta}>
                  {whenShort(r.startedAt)} · {duration(r.durationSec)}
                  {r.exitCode !== null && ` · 종료 코드 ${r.exitCode}`}
                </span>
              </button>
              <span className={s.runActions}>
                {r.state === 'running' && (
                  <button type="button" className={s.actBtnPlain} onClick={() => setStopping(r)}>
                    중지
                  </button>
                )}
                {r.state !== 'running' && (
                  <button type="button" className={s.actBtnPlain} onClick={() => setDialog({ open: true, from: r })}>
                    {r.state === 'cut' ? '이어서 실행…' : '다시 실행…'}
                  </button>
                )}
              </span>
            </div>
          ))}
        </section>
      </div>

      {current && <RunDetail project={project.name} run={current} onClose={() => pick('')} />}

      <NewRunDialog
        key={dialog.from?.id ?? (dialog.open ? 'new' : 'closed')}
        open={dialog.open}
        from={dialog.from}
        project={project}
        trees={trees}
        onClose={() => setDialog({ open: false })}
        onStarted={(id) => {
          setDialog({ open: false })
          pick(id)
        }}
      />
      <StopDialog project={project.name} run={stopping} onClose={() => setStopping(null)} />
    </div>
  )
}

function RunDetail({ project, run, onClose }: { project: string; run: Run; onClose: () => void }) {
  const live = run.state === 'running'
  const log = useQuery(runLogQuery(project, run.id, live))
  const metrics = useQuery(runMetricsQuery(project, run.id, live))
  const [copied, setCopied] = useState(false)
  const last = metrics.data?.last ?? {}

  return (
    <section aria-label={`${run.id} 로그`} className={s.logPanel}>
      <div className={s.logHead}>
        <b className={s.mono}>{run.id}</b>
        <RunStatePill run={run} />
        {run.reason && <span className={s.muted}>{run.reason}</span>}
        <span className={s.logSpacer} />
        {live && run.attach && (
          <button
            type="button"
            className={s.actBtnPlain}
            title={run.attach}
            onClick={() => copyText(run.attach).then(setCopied)}
          >
            {copied ? '복사했어요' : '터미널에서 붙기 · 복사'}
          </button>
        )}
        <button type="button" className={s.actBtnPlain} onClick={onClose}>
          닫기
        </button>
      </div>
      <div className={s.logMeta}>
        <span className={s.mono}>{run.command}</span>
        <span>
          conda {run.env || '없이'} · 위치 {run.cwd === '.' ? '프로젝트 루트' : run.cwd}
        </span>
        <span>
          지표{' '}
          {metrics.data?.file ? (
            <>
              <span className={s.mono}>{metrics.data.file}</span> ·{' '}
              {Object.entries(last)
                .slice(0, 6)
                .map(([k, v]) => `${k} ${v}`)
                .join(' · ') || '값 없음'}
            </>
          ) : (
            <span className={s.muted}>파일 없음 ({(metrics.data?.rules ?? []).join(', ')})</span>
          )}
        </span>
      </div>
      <pre className={s.logText} aria-live={live ? 'polite' : undefined}>
        {log.data?.text || (log.isPending ? '불러오는 중이에요…' : '로그가 비어 있어요.')}
      </pre>
    </section>
  )
}

function NewRunDialog({
  open,
  from,
  project,
  trees,
  onClose,
  onStarted,
}: {
  open: boolean
  from?: Run
  project: ProjectDetail
  trees?: WorktreeList
  onClose: () => void
  onStarted: (id: string) => void
}) {
  const start = useStartRun(project.name)
  const [command, setCommand] = useState(from?.command ?? project.settings.commands[0] ?? '')
  const [env, setEnv] = useState(from?.env ?? project.settings.condaEnv)
  const [cwd, setCwd] = useState(from?.cwd && from.cwd !== '.' ? from.cwd : '')
  const [name, setName] = useState(from?.name ?? '')
  // "시간 정해서 실행" — 같은 값으로 예약 창을 열어요
  const [scheduling, setScheduling] = useState(false)

  const places = [
    { rel: '', label: `프로젝트 루트${project.git.state === 'ok' ? ` (${project.git.branch})` : ''}` },
    ...(trees?.state === 'ok'
      ? trees.worktrees
          .filter((w) => !w.primary && w.rel)
          .map((w) => ({ rel: w.rel as string, label: `${w.branch || w.head} · ${w.rel}` }))
      : []),
  ]
  const shown = env.trim()
    ? `conda run -s -n ${env.trim()} bash -c '${command}'`
    : `bash -c '${command}'`

  if (scheduling) {
    return (
      <ScheduleDialog
        open
        seed={{ kind: 'command', project: project.name, tree: cwd, command, env: env.trim(), name: name.trim() }}
        onClose={() => {
          setScheduling(false)
          onClose()
        }}
      />
    )
  }

  return (
    <Dialog
      open={open}
      title={from ? `${from.id} 다시 실행` : '새 실행'}
      confirmLabel="지금 실행"
      busy={start.isPending}
      error={errText(start.error)}
      onClose={() => {
        start.reset()
        onClose()
      }}
      onConfirm={() =>
        start.mutate(
          { command, env: env.trim(), cwd, name: name.trim() },
          { onSuccess: (run) => onStarted(run.id) },
        )
      }
    >
      <label className={ds.field}>
        명령
        <input
          className={ds.input}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          list="run-commands"
          placeholder="python src/train.py --config configs/r16.yaml"
          autoFocus
          required
        />
        <datalist id="run-commands">
          {project.settings.commands.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </label>
      <label className={ds.field}>
        conda 환경 (비우면 conda 없이)
        <input className={ds.input} value={env} onChange={(e) => setEnv(e.target.value)} placeholder="lora-env" />
      </label>
      <label className={ds.field}>
        위치
        <select className={ds.input} value={cwd} onChange={(e) => setCwd(e.target.value)}>
          {places.map((p) => (
            <option key={p.rel || '.'} value={p.rel}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <label className={ds.field}>
        이름 (선택)
        <input className={ds.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="sweep-lr" />
      </label>
      <span className={s.muted}>
        실제로 도는 명령: <span className={s.mono}>{shown}</span> — tmux 안에서 돌고 로그는{' '}
        <span className={s.mono}>.labremote/runs/</span>에 남아요. 접속이 끊겨도 계속 돌아요.
      </span>
      {from && from.state === 'cut' && (
        <span className={s.muted}>
          체크포인트에서 이어 가려면 명령에 직접 재개 옵션을 붙여 주세요. lab.remote는 명령을 바꾸지 않아요.
        </span>
      )}
      <button type="button" className={s.linkBtn} disabled={!command.trim()} onClick={() => setScheduling(true)}>
        시간 정해서 실행…
      </button>
    </Dialog>
  )
}

function StopDialog({ project, run, onClose }: { project: string; run: Run | null; onClose: () => void }) {
  const stop = useStopRun()
  const [force, setForce] = useState(false)
  return (
    <Dialog
      open={run !== null}
      title={run ? `${run.id} 중지` : '중지'}
      confirmLabel={force ? '강제 중지' : '중지'}
      tone="danger"
      busy={stop.isPending}
      error={errText(stop.error)}
      onClose={() => {
        stop.reset()
        setForce(false)
        onClose()
      }}
      onConfirm={() =>
        run &&
        stop.mutate(
          { project, id: run.id, force },
          {
            onSuccess: () => {
              setForce(false)
              onClose()
            },
          },
        )
      }
    >
      <span>Ctrl+C를 보내요. 프로그램이 체크포인트를 저장하고 스스로 끝날 시간을 줘요.</span>
      <label className={ds.check}>
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
        <span>강제 중지 — 바로 끝내요. 체크포인트를 못 남길 수 있어요.</span>
      </label>
    </Dialog>
  )
}
