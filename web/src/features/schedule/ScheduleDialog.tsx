import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { projectsQuery, worktreesQuery } from '@/api/projects'
import { useScheduleActions } from '@/api/schedules'
import type { Repeat, Schedule, ScheduleInput, ScheduleKind } from '@/api/schedules'
import type { ModeId } from '@/api/agents'
import { ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds } from '@/components'
import s from './Schedule.module.css'

/** epoch 초 ↔ <input type="datetime-local"> 값 (현지 시각) */
const toLocal = (sec: number) => {
  const d = new Date(sec * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const fromLocal = (v: string) => new Date(v).getTime() / 1000

/** 다음 정각 */
const nextHour = () => {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d.getTime() / 1000
}

export interface ScheduleSeed {
  kind?: ScheduleKind
  project?: string
  tree?: string
  command?: string
  env?: string
  prompt?: string
  name?: string
}

/**
 * 예약 만들기 · 고치기 — Dashboard Schedule과 IDE 실행 탭의 "시간 정해서 실행…"이 같은 창을 써요.
 * 시각으로만 걸어요(연쇄 예약 없음).
 */
export function ScheduleDialog({
  open,
  onClose,
  edit,
  seed,
}: {
  open: boolean
  onClose: () => void
  edit?: Schedule
  seed?: ScheduleSeed
}) {
  const { create, update } = useScheduleActions()
  const list = useQuery(projectsQuery())
  const init = edit ?? seed ?? {}
  const [kind, setKind] = useState<ScheduleKind>(init.kind ?? 'command')
  const [project, setProject] = useState(init.project ?? '')
  const [tree, setTree] = useState(init.tree ?? '')
  const [command, setCommand] = useState(init.command ?? '')
  const [env, setEnv] = useState(init.env ?? '')
  const [prompt, setPrompt] = useState(init.prompt ?? '')
  const [name, setName] = useState(init.name ?? '')
  const [when, setWhen] = useState(toLocal(edit?.at ?? nextHour()))
  const [repeat, setRepeat] = useState<Repeat>(edit?.repeat ?? 'once')
  const proj = project || list.data?.projects[0]?.name || ''
  const trees = useQuery({ ...worktreesQuery(proj), enabled: !!proj })
  const places = trees.data?.state === 'ok' ? trees.data.worktrees.filter((w) => w.rel !== null) : []
  const busy = create.isPending || update.isPending
  const error = [create.error, update.error].find(Boolean)

  const submit = () => {
    const body: ScheduleInput = {
      name: name.trim() || (kind === 'command' ? command.trim().split(/\s+/).slice(0, 3).join(' ') : prompt.trim().slice(0, 30)),
      kind,
      project: proj,
      tree,
      command: kind === 'command' ? command : '',
      env: kind === 'command' ? env.trim() : '',
      prompt: kind === 'agent' ? prompt : '',
      mode: (edit?.mode ?? 'manual') as ModeId,
      model: edit?.model ?? '',
      effort: edit?.effort ?? '',
      at: fromLocal(when),
      repeat,
      enabled: true,
    }
    if (edit) update.mutate({ id: edit.id, ...body }, { onSuccess: onClose })
    else create.mutate(body, { onSuccess: onClose })
  }

  return (
    <Dialog
      open={open}
      title={edit ? '예약 고치기' : '예약 만들기'}
      confirmLabel={edit ? '저장' : '예약하기'}
      busy={busy}
      error={error instanceof ApiError ? error.message : error ? String(error) : undefined}
      onClose={() => {
        create.reset()
        update.reset()
        onClose()
      }}
      onConfirm={submit}
    >
      <div role="radiogroup" aria-label="예약 종류" className={s.seg}>
        {(
          [
            ['command', '명령'],
            ['agent', '에이전트'],
          ] as [ScheduleKind, string][]
        ).map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} className={s.segBtn} onClick={() => setKind(k)}>
            {label}
          </button>
        ))}
      </div>
      <label className={ds.field}>
        프로젝트
        <select className={ds.input} value={proj} onChange={(e) => (setProject(e.target.value), setTree(''))}>
          {(list.data?.projects ?? []).map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className={ds.field}>
        위치
        <select className={ds.input} value={tree} onChange={(e) => setTree(e.target.value)}>
          {places.length === 0 && <option value="">프로젝트 루트</option>}
          {places.map((w) => (
            <option key={w.path} value={w.rel === '.' ? '' : (w.rel ?? '')}>
              {w.branch || w.head} {w.rel && w.rel !== '.' ? `· ${w.rel}` : '· 프로젝트 루트'}
            </option>
          ))}
        </select>
      </label>
      {kind === 'command' ? (
        <>
          <label className={ds.field}>
            명령
            <input className={ds.input} value={command} onChange={(e) => setCommand(e.target.value)} placeholder="python src/train.py --config configs/r32.yaml" />
          </label>
          <label className={ds.field}>
            conda 환경 (비우면 conda 없이)
            <input className={ds.input} value={env} onChange={(e) => setEnv(e.target.value)} placeholder="lora-env" />
          </label>
        </>
      ) : (
        <label className={ds.field}>
          에이전트에게 보낼 요청
          <textarea className={ds.input} rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="이번 주 실험 결과를 README 표로 정리해 줘" />
        </label>
      )}
      <label className={ds.field}>
        이름
        <input className={ds.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="r32 학습" />
      </label>
      <div className={s.whenRow}>
        <label className={ds.field}>
          시각
          <input className={ds.input} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
        <label className={ds.field}>
          반복
          <select className={ds.input} value={repeat} onChange={(e) => setRepeat(e.target.value as Repeat)}>
            <option value="once">한 번</option>
            <option value="daily">매일</option>
            <option value="weekly">매주 (같은 요일)</option>
          </select>
        </label>
      </div>
      <span>
        {kind === 'command'
          ? '그때 GPU가 바쁘면 끝날 때까지 기다렸다가 시작하고 알려요.'
          : '그 시각에 세션을 열고 요청만 보내요. 승인이 필요하면 거기서 멈춰요.'}{' '}
        서버가 꺼져 있으면 돌지 않아요.
      </span>
    </Dialog>
  )
}
