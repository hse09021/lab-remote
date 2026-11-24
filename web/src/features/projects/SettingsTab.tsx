import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { condaEnvsQuery } from '@/api/conda'
import { papersQuery } from '@/api/papers'
import { useSaveSettings, useUnregisterProject } from '@/api/projects'
import type { ProjectDetail } from '@/api/projects'
import { ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds } from '@/components'
import s from './Projects.module.css'

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

export function SettingsTab({ project }: { project: ProjectDetail }) {
  // key로 프로젝트가 바뀌면 새로 그려요 — 입력 상태를 섞지 않게
  return <SettingsForm key={project.name} project={project} />
}

function SettingsForm({ project }: { project: ProjectDetail }) {
  const save = useSaveSettings(project.name)
  const st = project.settings
  const [env, setEnv] = useState(st.condaEnv)
  const [cmds, setCmds] = useState(st.commands.join('\n'))
  const [globs, setGlobs] = useState(st.metricGlobs.join('\n'))
  const [used, setUsed] = useState<string[]>(st.papers ?? [])
  const [paperFind, setPaperFind] = useState('')
  const [asking, setAsking] = useState(false)
  const envs = useQuery(condaEnvsQuery())
  const papers = useQuery(papersQuery())

  const samePapers = used.length === (st.papers ?? []).length && used.every((p) => (st.papers ?? []).includes(p))
  const dirty = env !== st.condaEnv || cmds !== st.commands.join('\n') || globs !== st.metricGlobs.join('\n') || !samePapers
  const payload = (share: boolean) => ({ condaEnv: env.trim(), commands: lines(cmds), metricGlobs: lines(globs), papers: used, share })

  // conda 환경 목록 — 지금 값이 목록에 없어도(지운 환경 · 다른 PC) 그대로 보여 줘요
  const envNames = (envs.data?.envs ?? []).map((e) => e.name)
  const envOptions = env && !envNames.includes(env) ? [env, ...envNames] : envNames
  const q = paperFind.trim().toLowerCase()
  const paperRows = (papers.data ?? []).filter((p) => !q || p.title.toLowerCase().includes(q) || p.id.toLowerCase().includes(q))
  const missing = used.filter((id) => papers.data && !papers.data.some((p) => p.id === id))
  const toggle = (id: string) => setUsed((old) => (old.includes(id) ? old.filter((x) => x !== id) : [...old, id]))

  return (
    <div className={s.settings}>
      <form
        className={s.settingsGrid}
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate(payload(st.share))
        }}
      >
        <label htmlFor="pj-env" className={s.settingsLabel}>
          기본 conda 환경
        </label>
        <span className={s.settingsRow}>
          {envs.isSuccess ? (
            <select id="pj-env" className={s.input} value={env} onChange={(e) => setEnv(e.target.value)}>
              <option value="">선택 안 함</option>
              {envOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                  {envNames.includes(n) ? '' : ' (목록에 없음)'}
                </option>
              ))}
            </select>
          ) : (
            // conda를 못 읽으면 직접 적어요
            <input id="pj-env" className={s.input} value={env} onChange={(e) => setEnv(e.target.value)} placeholder="lora-env" />
          )}
          <Link to="/settings/conda" className={s.actLink}>
            환경 관리
          </Link>
        </span>
        <label htmlFor="pj-cmd" className={s.settingsLabel}>
          자주 쓰는 실행 명령
        </label>
        <textarea
          id="pj-cmd"
          className={s.textarea}
          rows={2}
          value={cmds}
          onChange={(e) => setCmds(e.target.value)}
          placeholder="python src/train.py --config configs/r16.yaml"
        />
        <label htmlFor="pj-metric" className={s.settingsLabel}>
          지표 파일 찾기
        </label>
        <textarea
          id="pj-metric"
          className={s.textarea}
          rows={1}
          value={globs}
          onChange={(e) => setGlobs(e.target.value)}
          placeholder="runs/*/metrics.csv"
        />
        <label htmlFor="pj-papers" className={s.settingsLabel}>
          사용하는 논문
        </label>
        <div className={s.paperPick}>
          <input
            id="pj-papers"
            className={s.input}
            value={paperFind}
            onChange={(e) => setPaperFind(e.target.value)}
            placeholder={`vault 논문 ${papers.data?.length ?? 0}편에서 찾기`}
          />
          <div className={s.paperList} role="group" aria-label="사용하는 논문 선택">
            {papers.isSuccess && papers.data.length === 0 && (
              <span className={s.muted}>
                vault에 논문 노트가 없어요. vault 위치는 <Link to="/papers">Papers</Link>에서 설정해요.
              </span>
            )}
            {paperRows.map((p) => (
              <label key={p.id} className={s.paperItem}>
                <input type="checkbox" checked={used.includes(p.id)} onChange={() => toggle(p.id)} />
                <span>{p.title}</span>
              </label>
            ))}
            {missing.map((id) => (
              <label key={id} className={s.paperItem}>
                <input type="checkbox" checked onChange={() => toggle(id)} />
                <span>
                  {id} <span className={s.muted}>(vault에 없음)</span>
                </span>
              </label>
            ))}
          </div>
          <span className={s.muted}>
            선택한 논문은 Papers › Graph에서 "프로젝트에서 사용"으로 연결돼요. 지금 {used.length}편 선택했어요.
          </span>
        </div>
        <span />
        <span className={s.settingsRow}>
          <button type="submit" className={s.primaryBtn} disabled={!dirty || save.isPending}>
            {save.isPending ? '저장하는 중…' : '저장'}
          </button>
          <span className={s.muted}>명령과 지표 규칙은 한 줄에 하나씩 입력해요.</span>
          {save.isError && (
            <span role="alert" className={s.errText}>
              {save.error instanceof ApiError ? save.error.message : String(save.error)}
            </span>
          )}
        </span>
      </form>

      <div className={s.settingsNote}>
        이 설정은 프로젝트의 <span className={s.mono}>.labremote/settings.json</span>에 저장돼요. 시나리오는{' '}
        <span className={s.mono}>.labremote/scenarios/</span>, worktree는 <span className={s.mono}>.labremote/worktrees/</span>에
        있어요.
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={st.share}
        className={s.switchRow}
        disabled={save.isPending}
        onClick={() =>
          // 저장 안 한 입력은 섞지 않고, 저장된 값에서 이 스위치만 바꿔요
          save.mutate({ condaEnv: st.condaEnv, commands: st.commands, metricGlobs: st.metricGlobs, papers: st.papers ?? [], share: !st.share })
        }
      >
        <span className={s.switchText}>
          <span className={s.switchTitle}>repo에 포함하기</span>
          <span className={s.muted}>
            켜면 settings.json과 scenarios/만 git에 포함돼요. worktree와 실행 기록은 계속 제외돼요.
          </span>
        </span>
        <span aria-hidden="true" className={s.track} data-on={st.share}>
          <span className={s.knob} />
        </span>
      </button>

      <div className={s.dangerRow}>
        <span className={s.muted}>
          <b className={s.strong}>등록 해제</b> · lab.remote 목록에서만 제거되고 폴더와 파일은 그대로 남아요.{' '}
          <span className={s.mono}>.labremote</span> 폴더도 삭제할지는 한 번 더 확인해요.
        </span>
        <button type="button" className={s.dangerBtn} onClick={() => setAsking(true)}>
          등록 해제…
        </button>
      </div>

      <UnregisterDialog name={project.name} open={asking} onClose={() => setAsking(false)} />
    </div>
  )
}

function UnregisterDialog({ name, open, onClose }: { name: string; open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const unregister = useUnregisterProject()
  const [removeLabremote, setRemove] = useState(false)
  return (
    <Dialog
      open={open}
      title={`${name} 등록 해제`}
      confirmLabel="해제"
      tone="danger"
      busy={unregister.isPending}
      error={unregister.error instanceof ApiError ? unregister.error.message : undefined}
      onClose={onClose}
      onConfirm={() =>
        unregister.mutate(
          { name, removeLabremote },
          {
            onSuccess: () => {
              onClose()
              navigate('/projects', { replace: true })
            },
          },
        )
      }
    >
      <span>lab.remote 목록에서 제거돼요. 프로젝트 폴더와 파일은 그대로 남아요.</span>
      <label className={ds.check}>
        <input type="checkbox" checked={removeLabremote} onChange={(e) => setRemove(e.target.checked)} />
        <span>
          <span className={s.mono}>.labremote/</span>도 지우기 — 설정, Scenario, worktree 폴더가 함께 지워지고 되돌릴 수
          없어요.
        </span>
      </label>
    </Dialog>
  )
}
