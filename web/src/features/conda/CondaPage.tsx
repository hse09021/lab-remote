import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { condaEnvQuery, condaEnvsQuery, condaExportHref, parsePackages, useCondaActions, useCondaJob } from '@/api/conda'
import type { CondaEnvDetail, CondaJob, PackageInput } from '@/api/conda'
import { apiUrl, ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import s from './Conda.module.css'

/** Conda — docs/v3/mockups/Conda.dc.html */
const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : '')

export default function CondaPage() {
  const [params, setParams] = useSearchParams()
  const envs = useQuery(condaEnvsQuery())
  const list = envs.data?.envs ?? []
  const current = params.get('env') || list.find((e) => !e.protected)?.name || list[0]?.name || ''
  const [making, setMaking] = useState<{ open: boolean; clone?: string }>({ open: false })

  return (
    <div className={s.page}>
      <aside aria-label="환경 목록" className={s.aside}>
        <div className={s.asideHead}>
          <span className={s.asideTitle}>환경</span>
          <span className={s.muted}>{list.length}</span>
          <button type="button" className={s.addBtn} onClick={() => setMaking({ open: true })}>
            + 새 환경
          </button>
        </div>
        {envs.isPending && <LoadingState label="환경을 불러오는 중이에요" />}
        {envs.isError && <ErrorState error={envs.error} onRetry={() => envs.refetch()} />}
        {list.map((e) => (
          <button
            key={e.name}
            type="button"
            aria-current={e.name === current ? 'true' : undefined}
            className={s.envItem}
            onClick={() => setParams({ env: e.name }, { replace: true })}
          >
            <span className={s.envName}>{e.name}</span>
            {e.protected && <span className={s.tag}>보호됨</span>}
            {e.usedBy.length > 0 && <span className={s.tagBusy}>사용 중</span>}
          </button>
        ))}
        <p className={s.asideFoot}>conda 설치 폴더 아래 환경만 다뤄요. conda 설정(.condarc)은 바꾸지 않아요.</p>
      </aside>
      <main className={s.main}>{current ? <EnvPanel key={current} name={current} onClone={() => setMaking({ open: true, clone: current })} /> : null}</main>
      <CreateDialog key={`${making.open}-${making.clone ?? ''}`} open={making.open} clone={making.clone} onClose={() => setMaking({ open: false })} />
    </div>
  )
}

function EnvPanel({ name, onClone }: { name: string; onClone: () => void }) {
  const env = useQuery(condaEnvQuery(name))
  if (env.isPending) return <LoadingState label="패키지를 불러오는 중이에요" />
  if (env.isError) return <ErrorState error={env.error} onRetry={() => env.refetch()} />
  const d = env.data
  return (
    <div className={s.panel}>
      <div className={s.head}>
        <div>
          <h1 className={s.title}>{d.name}</h1>
          <div className={s.meta}>
            <span className={s.mono}>{d.prefix}</span> · Python {d.python || '없음'} · 패키지 {d.packages.length}
          </div>
        </div>
        <div className={s.headActions}>
          <a className={s.ghostBtn} href={apiUrl(condaExportHref(d.name))} download>
            environment.yml 내보내기
          </a>
          <button type="button" className={s.ghostBtn} onClick={onClone}>
            복제…
          </button>
        </div>
      </div>

      {d.protected ? (
        <div role="status" className={s.banner}>
          <b>지울 수 없는 환경이에요</b>
          <span>
            {d.name === 'base'
              ? 'conda 의 기본 환경이라 지우거나 패키지를 바꾸지 않아요. 보기만 할 수 있어요.'
              : d.name === 'labremote'
                ? 'lab.remote 서버가 쓰는 환경이에요. 지우면 lab.remote 가 멈춰서 여기서는 막아 둬요.'
                : d.protectedReason}
          </span>
        </div>
      ) : d.usedBy.length > 0 ? (
        <div role="status" className={s.banner}>
          <b>사용 중이라 잠겨 있어요</b>
          <span>
            {d.usedBy.join(', ')} 이 이 환경으로 학습 중이에요. 패키지를 바꾸면 학습이 깨질 수 있어서 끝날 때까지 설치 · 제거 · 삭제를 막아요.
          </span>
          <Link to={`/projects/${encodeURIComponent(d.usedBy[0].split(' · ')[0])}?tab=work&run=${d.usedBy[0].split(' · ')[1]}`}>학습 보기</Link>
        </div>
      ) : null}

      <InstallBox env={d} />
      <PackageTable env={d} />
      {!d.protected && <DeleteBox env={d} />}
    </div>
  )
}

/** 미리 보기 → 확인 → 실제 작업. 미리 보기 결과를 사람이 본 다음에만 실행 버튼이 켜져요. */
function useTwoStep() {
  const { change } = useCondaActions()
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const preview = useCondaJob(previewId)
  const run = useCondaJob(runId)
  return { change, previewId, setPreviewId, runId, setRunId, preview, run }
}

function JobResult({ job, done }: { job?: CondaJob; done: string }) {
  if (!job) return null
  if (job.state === 'running') return <div className={s.notice}>{job.dry ? '바뀌는 것을 계산하는 중이에요 (dry-run)…' : '하는 중이에요… 몇 분 걸릴 수 있어요.'}</div>
  if (job.state === 'failed') return <div className={s.warn}>실패했어요: {job.error}</div>
  if (job.dry) {
    return (
      <div className={s.preview}>
        <div className={s.previewHead}>미리 보기 · 이렇게 바뀌어요 (아직 아무것도 바꾸지 않았어요)</div>
        {(job.changes ?? []).length === 0 && <div className={s.muted}>바뀌는 게 없어요 (이미 있거나 최신이에요).</div>}
        {(job.changes ?? []).map((c, i) => (
          <div key={i} className={s.change} data-action={c.action}>
            <span className={s.changeTag}>{c.action}</span>
            <span className={s.mono}>{c.name}</span>
            <span className={s.mono}>
              {c.from && c.to ? `${c.from} → ${c.to}` : c.to || c.from}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return <div className={s.ok}>{done}</div>
}

function InstallBox({ env }: { env: CondaEnvDetail }) {
  const t = useTwoStep()
  const [text, setText] = useState('')
  const [tool, setTool] = useState<'conda' | 'pip'>('pip')
  const pkgs = parsePackages(text)
  const locked = !!env.lock
  const previewed = t.preview.data?.state === 'done'
  return (
    <section aria-label="패키지 설치" className={s.card}>
      <h2 className={s.h2}>패키지 설치</h2>
      <div className={s.row}>
        <label className={s.srOnly} htmlFor="pkg-input">
          패키지 이름
        </label>
        <input
          id="pkg-input"
          className={s.input}
          value={text}
          disabled={locked}
          onChange={(e) => {
            setText(e.target.value)
            t.setPreviewId(null)
            t.setRunId(null)
          }}
          placeholder="패키지 이름 (예: timm==1.0.11 peft)"
        />
        <div role="radiogroup" aria-label="설치 방법" className={s.seg}>
          {(['conda', 'pip'] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={tool === k}
              className={s.segBtn}
              disabled={locked}
              onClick={() => (setTool(k), t.setPreviewId(null), t.setRunId(null))}
            >
              {k}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={s.ghostBtn}
          disabled={locked || pkgs.length === 0 || t.change.isPending}
          onClick={() =>
            t.change.mutate({ env: env.name, tool, action: 'install', packages: pkgs, dry: true }, { onSuccess: (j) => (t.setPreviewId(j.id), t.setRunId(null)) })
          }
        >
          바뀌는 것 미리 보기
        </button>
      </div>
      {t.change.error && <div className={s.warn}>{errText(t.change.error)}</div>}
      <JobResult job={t.preview.data} done="" />
      {previewed && !t.runId && (
        <div className={s.row}>
          <button
            type="button"
            className={s.primary}
            disabled={locked || t.change.isPending}
            onClick={() => t.change.mutate({ env: env.name, tool, action: 'install', packages: pkgs, dry: false }, { onSuccess: (j) => t.setRunId(j.id) })}
          >
            설치
          </button>
          <span className={s.muted}>
            설치 기록은 lab.remote 데이터 폴더에 남아요. pip 는 휠만 받고 캐시를 쓰지 않아요(설치할 때 코드가 돌지 않게).
          </span>
        </div>
      )}
      <JobResult job={t.run.data} done="설치했어요." />
      {locked && <div className={s.muted}>{env.lock}</div>}
    </section>
  )
}

function PackageTable({ env }: { env: CondaEnvDetail }) {
  const [q, setQ] = useState('')
  const [target, setTarget] = useState<{ pkg: PackageInput; source: 'conda' | 'pip'; action: 'update' | 'remove' } | null>(null)
  const shown = env.packages.filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
  return (
    <section aria-label="패키지 목록" className={s.card}>
      <div className={s.cardHead}>
        <h2 className={s.h2}>
          패키지 <span className={s.muted}>{env.packages.length}</span>
        </h2>
        <label className={s.srOnly} htmlFor="pkg-search">
          패키지 검색
        </label>
        <input id="pkg-search" className={s.search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="패키지 검색" />
      </div>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th>이름</th>
              <th>버전</th>
              <th>출처</th>
              <th>동작</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, 400).map((p) => (
              <tr key={`${p.source}:${p.name}`}>
                <td className={s.mono}>{p.name}</td>
                <td className={s.mono}>{p.version}</td>
                <td>
                  <span className={s.source} data-source={p.source}>
                    {p.source === 'pip' ? 'pip' : p.channel}
                  </span>
                </td>
                <td className={s.actions}>
                  <button type="button" className={s.link} disabled={!!env.lock} onClick={() => setTarget({ pkg: { name: p.name }, source: p.source, action: 'update' })}>
                    업데이트
                  </button>
                  <button type="button" className={s.linkDanger} disabled={!!env.lock} onClick={() => setTarget({ pkg: { name: p.name }, source: p.source, action: 'remove' })}>
                    제거
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > 400 && <div className={s.muted}>앞의 400개만 보여요. 검색으로 좁혀 주세요.</div>}
      {target && <ChangeDialog key={`${target.pkg.name}-${target.action}`} env={env.name} target={target} onClose={() => setTarget(null)} />}
    </section>
  )
}

function ChangeDialog({
  env,
  target,
  onClose,
}: {
  env: string
  target: { pkg: PackageInput; source: 'conda' | 'pip'; action: 'update' | 'remove' }
  onClose: () => void
}) {
  const t = useTwoStep()
  const { mutate } = t.change
  const { setPreviewId } = t
  const started = useRef(false)
  // 창이 열리면 먼저 미리 보기(dry-run)부터 — 개발 모드에서 두 번 돌지 않게 한 번만
  useEffect(() => {
    if (started.current) return
    started.current = true
    mutate({ env, tool: target.source, action: target.action, packages: [target.pkg], dry: true }, { onSuccess: (j) => setPreviewId(j.id) })
  }, [env, target, mutate, setPreviewId])
  const label = target.action === 'update' ? '업데이트' : '제거'
  const ready = t.preview.data?.state === 'done' && !t.runId
  return (
    <Dialog
      open
      title={`${target.pkg.name} ${label}`}
      confirmLabel={label}
      tone={target.action === 'remove' ? 'danger' : 'accent'}
      busy={!ready || t.change.isPending}
      error={errText(t.change.error) || undefined}
      onClose={onClose}
      onConfirm={() => t.change.mutate({ env, tool: target.source, action: target.action, packages: [target.pkg], dry: false }, { onSuccess: (j) => t.setRunId(j.id) })}
    >
      <JobResult job={t.preview.data} done="" />
      <JobResult job={t.run.data} done={`${label}했어요. 닫아도 돼요.`} />
    </Dialog>
  )
}

function DeleteBox({ env }: { env: CondaEnvDetail }) {
  const navigate = useNavigate()
  const { remove } = useCondaActions()
  const [confirm, setConfirm] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useCondaJob(jobId)
  return (
    <section aria-label="환경 삭제" className={s.dangerCard}>
      <h2 className={s.h2}>환경 삭제</h2>
      <p className={s.muted}>되돌릴 수 없어요. 지우기 전에 environment.yml 을 lab.remote 데이터 폴더에 백업해 둬요.</p>
      <div className={s.row}>
        <label className={s.srOnly} htmlFor="del-name">
          삭제 확인용 환경 이름
        </label>
        <input id="del-name" className={s.input} value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={`지우려면 ${env.name} 라고 적어 주세요`} disabled={!!env.lock} />
        <button
          type="button"
          className={s.danger}
          disabled={confirm !== env.name || !!env.lock || remove.isPending || job.data?.state === 'running'}
          onClick={() => remove.mutate({ env: env.name, confirm }, { onSuccess: (j) => setJobId(j.id) })}
        >
          삭제
        </button>
      </div>
      {remove.error && <div className={s.warn}>{errText(remove.error)}</div>}
      {job.data?.state === 'running' && <div className={s.notice}>백업하고 지우는 중이에요…</div>}
      {job.data?.state === 'failed' && <div className={s.warn}>지우지 못했어요: {job.data.error}</div>}
      {job.data?.state === 'done' && (
        <div className={s.ok}>
          지웠어요. 백업: <span className={s.mono}>{job.data.backup}</span>{' '}
          <button type="button" className={s.link} onClick={() => navigate('/settings/conda', { replace: true })}>
            목록으로
          </button>
        </div>
      )}
    </section>
  )
}

function CreateDialog({ open, clone, onClose }: { open: boolean; clone?: string; onClose: () => void }) {
  const { create } = useCondaActions()
  const [name, setName] = useState(clone ? `${clone}-copy` : '')
  const [python, setPython] = useState('3.11')
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useCondaJob(jobId)
  return (
    <Dialog
      open={open}
      title={clone ? `${clone} 복제` : '새 환경'}
      confirmLabel={clone ? '복제' : '만들기'}
      busy={create.isPending || job.data?.state === 'running'}
      error={errText(create.error) || (job.data?.state === 'failed' ? job.data.error : undefined)}
      onClose={onClose}
      onConfirm={() => create.mutate({ name: name.trim(), python, clone: clone ?? '' }, { onSuccess: (j) => setJobId(j.id) })}
    >
      <label className={ds.field}>
        환경 이름
        <input className={ds.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="vit-env" autoFocus />
      </label>
      {!clone && (
        <label className={ds.field}>
          Python 버전
          <input className={ds.input} value={python} onChange={(e) => setPython(e.target.value)} placeholder="3.11" />
        </label>
      )}
      {job.data?.state === 'running' && <span>만드는 중이에요… 몇 분 걸릴 수 있어요.</span>}
      {job.data?.state === 'done' && <span>만들었어요. 닫아도 돼요.</span>}
      <span>conda 기본 채널 설정을 그대로 써요(.condarc 는 바꾸지 않아요).</span>
    </Dialog>
  )
}
