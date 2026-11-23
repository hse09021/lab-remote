import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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
  // key 로 프로젝트가 바뀌면 새로 그려요 — 입력 상태를 섞지 않게
  return <SettingsForm key={project.name} project={project} />
}

function SettingsForm({ project }: { project: ProjectDetail }) {
  const save = useSaveSettings(project.name)
  const st = project.settings
  const [env, setEnv] = useState(st.condaEnv)
  const [cmds, setCmds] = useState(st.commands.join('\n'))
  const [globs, setGlobs] = useState(st.metricGlobs.join('\n'))
  const [asking, setAsking] = useState(false)

  const dirty = env !== st.condaEnv || cmds !== st.commands.join('\n') || globs !== st.metricGlobs.join('\n')
  const payload = (share: boolean) => ({ condaEnv: env.trim(), commands: lines(cmds), metricGlobs: lines(globs), share })

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
          <input id="pj-env" className={s.input} value={env} onChange={(e) => setEnv(e.target.value)} placeholder="lora-env" />
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
        <span />
        <span className={s.settingsRow}>
          <button type="submit" className={s.primaryBtn} disabled={!dirty || save.isPending}>
            {save.isPending ? '저장하는 중…' : '저장'}
          </button>
          <span className={s.muted}>명령과 지표 규칙은 한 줄에 하나씩 적어요.</span>
          {save.isError && (
            <span role="alert" className={s.errText}>
              {save.error instanceof ApiError ? save.error.message : String(save.error)}
            </span>
          )}
        </span>
      </form>

      <div className={s.settingsNote}>
        이 설정은 프로젝트의 <span className={s.mono}>.labremote/settings.json</span> 에 저장돼요. 시나리오는{' '}
        <span className={s.mono}>.labremote/scenarios/</span>, worktree 는 <span className={s.mono}>.labremote/worktrees/</span>{' '}
        에 있어요.
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={st.share}
        className={s.switchRow}
        disabled={save.isPending}
        onClick={() =>
          // 저장 안 한 입력은 섞지 않고, 저장된 값에서 이 스위치만 바꿔요
          save.mutate({ condaEnv: st.condaEnv, commands: st.commands, metricGlobs: st.metricGlobs, share: !st.share })
        }
      >
        <span className={s.switchText}>
          <span className={s.switchTitle}>repo 에 같이 올리기</span>
          <span className={s.muted}>
            켜면 settings.json 과 scenarios/ 만 git 에 올라가요. worktree 와 실행 기록은 계속 빠져요.
          </span>
        </span>
        <span aria-hidden="true" className={s.track} data-on={st.share}>
          <span className={s.knob} />
        </span>
      </button>

      <div className={s.dangerRow}>
        <span className={s.muted}>
          <b className={s.strong}>등록 해제</b> · lab.remote 목록에서만 빠지고 폴더와 파일은 그대로 남아요.{' '}
          <span className={s.mono}>.labremote</span> 폴더도 지울지는 한 번 더 물어봐요.
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
      <span>lab.remote 목록에서 빠져요. 프로젝트 폴더와 파일은 그대로 남아요.</span>
      <label className={ds.check}>
        <input type="checkbox" checked={removeLabremote} onChange={(e) => setRemove(e.target.checked)} />
        <span>
          <span className={s.mono}>.labremote/</span> 도 지우기 — 설정 · Scenario · worktree 폴더가 함께 지워지고 되돌릴 수
          없어요.
        </span>
      </label>
    </Dialog>
  )
}
