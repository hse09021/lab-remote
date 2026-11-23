import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  projectQuery,
  projectsQuery,
  usePinProject,
  useRegisterProject,
  worktreesQuery,
} from '@/api/projects'
import type { GitSummary, ProjectRow } from '@/api/projects'
import { ApiError } from '@/api/client'
import { sessionsQuery } from '@/api/agents'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import { agoShort, whenShort } from '@/lib/time'
import { FilesTab } from './FilesTab'
import { WorktreesTab } from './WorktreesTab'
import { SettingsTab } from './SettingsTab'
import { RunsTab } from './RunsTab'
import s from './Projects.module.css'

type Tab = 'files' | 'worktrees' | 'work' | 'settings'
const TABS: Tab[] = ['files', 'worktrees', 'work', 'settings']

/** 목록의 작은 글 — 세션·실행이 붙기 전(2·3단계)에는 git 상태로 채워요 */
export function gitLine(git: GitSummary, { long = false } = {}): string {
  if (git.state === 'ok') {
    const head = `${git.branch || '(브랜치 없음)'} · ${git.head || '커밋 없음'}`
    if (long) return `${head} · 변경 ${git.changed}`
    return git.changed ? `변경 ${git.changed} · 커밋 전` : head
  }
  if (git.state === 'none') return 'git 저장소 아님'
  if (git.state === 'missing') return '폴더가 없어요'
  if (git.state === 'refused') return 'git 을 안 돌렸어요 (.git 설정)'
  return 'git 을 못 읽었어요'
}

const toneOf = (p: ProjectRow) => (p.agents.ask > 0 ? 'ask' : p.runs.running.length > 0 || p.agents.working > 0 ? 'work' : 'idle')

/** 실행 한 줄 — 돌고 있으면 그것, 아니면 마지막 실행이 실패·끊김일 때만 */
function runLine(p: ProjectRow): string | null {
  if (p.agents.ask > 0) return `답 필요 ${p.agents.ask}${p.runs.running.length ? ' · 학습 중' : ''}`
  if (p.agents.working > 0 && !p.runs.running.length) return `작업 중 ${p.agents.working}`
  const running = p.runs.running
  if (running.length === 1) return `${running[0].name || running[0].id} 학습 중`
  if (running.length > 1) return `학습 ${running.length}개 실행 중`
  const last = p.runs.last
  if (last && (last.state === 'failed' || last.state === 'cut')) return `${last.name || last.id} ${last.stateLabel}`
  return null
}

function runChip(p: ProjectRow): string {
  const running = p.runs.running
  if (running.length) return running.map((r) => `${r.name || r.id} 실행 중`).join(' · ')
  const last = p.runs.last
  if (!last) return '실행 없음'
  return `${last.name || last.id} ${last.stateLabel} · ${whenShort(last.endedAt ?? last.startedAt)}`
}

export default function ProjectsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const list = useQuery(projectsQuery())
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'recent' | 'name'>('recent')
  const [registering, setRegistering] = useState(false)

  const projects = useMemo(() => list.data?.projects ?? [], [list.data])

  // /projects 로 오면 가장 최근 프로젝트를 열어요
  useEffect(() => {
    // 쿼리(?tab=work 등)는 그대로 들고 가요 — Dashboard 의 "새 실행" 이 쓰는 길
    if (!id && projects.length > 0)
      navigate(`/projects/${encodeURIComponent(projects[0].name)}${window.location.search}`, { replace: true })
  }, [id, projects, navigate])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const hit = projects.filter((p) => !q || p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q))
    return sort === 'name' ? [...hit].sort((a, b) => a.name.localeCompare(b.name)) : hit
  }, [projects, query, sort])

  const pinned = shown.filter((p) => p.pinned)
  const rest = shown.filter((p) => !p.pinned)

  return (
    <div className={s.page}>
      <aside aria-label="프로젝트 목록" className={s.aside}>
        <div className={s.asideHead}>
          <span className={s.asideTitle}>프로젝트</span>
          <span className={s.count}>{projects.length}</span>
          <button type="button" className={s.addBtn} onClick={() => setRegistering(true)}>
            + 폴더 등록
          </button>
        </div>
        <div className={s.asideTools}>
          <label htmlFor="pj-search" className={s.srOnly}>
            프로젝트 검색
          </label>
          <input
            id="pj-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="이름 · 경로 검색"
            className={s.search}
          />
          <div role="group" aria-label="정렬" className={s.seg}>
            {(['recent', 'name'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)} className={s.segBtn}>
                {k === 'recent' ? '최근 활동' : '이름'}
              </button>
            ))}
          </div>
        </div>

        <div className={s.list}>
          {list.isPending && <LoadingState label="프로젝트를 불러오는 중이에요" />}
          {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
          {pinned.length > 0 && <div className={s.group}>고정</div>}
          {pinned.map((p) => (
            <ProjectItem key={p.name} p={p} current={p.name === id} />
          ))}
          {projects.length > 0 && <div className={s.group}>전체</div>}
          {rest.map((p) => (
            <ProjectItem key={p.name} p={p} current={p.name === id} />
          ))}
          {list.isSuccess && projects.length > 0 && shown.length === 0 && (
            <div className={s.noMatch}>맞는 프로젝트가 없어요.</div>
          )}
        </div>
        <div className={s.asideFoot}>
          등록한 폴더만 읽어요. lab.remote 가 쓰는 건 각 프로젝트의 <span className={s.mono}>.labremote/</span>{' '}
          하나뿐이에요.
        </div>
      </aside>

      <main className={s.main}>
        {id ? (
          <ProjectDetail name={id} />
        ) : (
          list.isSuccess &&
          projects.length === 0 && (
            <div className={s.empty}>
              <h1 className={s.emptyTitle}>등록한 프로젝트가 없어요</h1>
              <p className={s.emptyText}>
                연구 폴더를 등록하면 파일 · git · worktree 를 여기서 봐요. 폴더 안에는{' '}
                <span className={s.mono}>.labremote/</span> 하나만 생겨요.
              </p>
              <button type="button" className={s.primaryBtn} onClick={() => setRegistering(true)}>
                폴더 등록
              </button>
            </div>
          )
        )}
      </main>

      <RegisterDialog open={registering} onClose={() => setRegistering(false)} />
    </div>
  )
}

function ProjectItem({ p, current }: { p: ProjectRow; current: boolean }) {
  return (
    <Link
      to={`/projects/${encodeURIComponent(p.name)}`}
      aria-current={current ? 'page' : undefined}
      className={s.item}
    >
      {/* 상태 점: 학습이 돌면 작업 중. 답 필요는 세션이 붙는 3단계부터 */}
      <span aria-hidden="true" className={s.itemDot} data-tone={toneOf(p)} />
      <span className={s.itemText}>
        <span className={s.itemName}>{p.name}</span>
        <span className={s.itemSub} data-tone={toneOf(p)}>{!p.exists ? '폴더가 없어요' : (runLine(p) ?? gitLine(p.git))}</span>
      </span>
      <span className={s.itemAgo}>{agoShort(p.activityAt)}</span>
    </Link>
  )
}

function RegisterDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const register = useRegisterProject()
  const [path, setPath] = useState('')
  const [name, setName] = useState('')

  const close = () => {
    register.reset()
    setPath('')
    setName('')
    onClose()
  }

  return (
    <Dialog
      open={open}
      title="폴더 등록"
      confirmLabel="등록"
      busy={register.isPending}
      error={register.error instanceof ApiError ? register.error.message : register.error ? String(register.error) : undefined}
      onClose={close}
      onConfirm={() =>
        register.mutate(
          { path, name },
          {
            onSuccess: (made) => {
              close()
              navigate(`/projects/${encodeURIComponent(made.name)}`)
            },
          },
        )
      }
    >
      <label className={ds.field}>
        이 컴퓨터의 폴더 경로
        <input
          className={ds.input}
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="~/projects/lora-rank-ablation"
          autoFocus
          required
        />
      </label>
      <label className={ds.field}>
        이름 (비우면 폴더 이름으로)
        <input className={ds.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="lora-rank-ablation" />
      </label>
      <span>
        폴더 안에 <span className={s.mono}>.labremote/</span> 를 만들어요. 스스로 git에서 빠지고, 프로젝트의{' '}
        <span className={s.mono}>.gitignore</span> 는 건드리지 않아요.
      </span>
    </Dialog>
  )
}

function ProjectDetail({ name }: { name: string }) {
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab') as Tab | null
  const tab: Tab = tabParam && TABS.includes(tabParam) ? tabParam : 'files'
  const detail = useQuery(projectQuery(name))
  const trees = useQuery(worktreesQuery(name))
  const pin = usePinProject()
  const sess = useQuery(sessionsQuery(name))
  const sessionCount = {
    total: sess.data?.sessions.length ?? 0,
    ask: (sess.data?.sessions ?? []).filter((x) => x.pending.length > 0).length,
  }

  if (detail.isPending) return <LoadingState label="프로젝트를 불러오는 중이에요" />
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
  const p = detail.data
  const treeCount = trees.data?.state === 'ok' ? trees.data.worktrees.length : p.git.state === 'ok' ? 1 : 0

  const pick = (t: Tab) => {
    const next = new URLSearchParams(params)
    next.set('tab', t)
    setParams(next, { replace: true })
  }

  const label: Record<Tab, string> = {
    files: '파일',
    worktrees: `worktree ${treeCount}`,
    work: '세션 · 실행',
    settings: '설정',
  }
  const base = `/projects/${encodeURIComponent(p.name)}`

  return (
    <>
      <div className={s.detailHead}>
        <div className={s.detailMain}>
          <div className={s.titleRow}>
            <span aria-hidden="true" className={s.bigDot} data-tone={toneOf(p)} />
            <h1 className={s.title}>{p.name}</h1>
            <button
              type="button"
              aria-pressed={p.pinned}
              className={s.pinBtn}
              onClick={() => pin.mutate({ name: p.name, pinned: !p.pinned })}
            >
              {p.pinned ? '고정됨' : '고정'}
            </button>
          </div>
          <div className={s.path}>{p.path}</div>
          <div className={s.chips}>
            <span className={s.chip}>{gitLine(p.git, { long: true })}</span>
            <span className={s.chip}>
              conda · <span className={s.mono}>{p.settings.condaEnv || '없음'}</span>
            </span>
            <span className={s.chip} data-on={sessionCount.ask > 0}>
              {sessionCount.total === 0 ? '세션 없음' : `세션 ${sessionCount.total}${sessionCount.ask ? ` · 답 필요 ${sessionCount.ask}` : ''}`}
            </span>
            <span className={s.chip} data-on={p.runs.running.length > 0}>
              {runChip(p)}
            </span>
          </div>
        </div>
        <Link to={`${base}/ide`} className={s.headLink}>
          IDE에서 열기
        </Link>
        <Link to={`${base}/ade`} className={s.headLink}>
          ADE 세션
        </Link>
      </div>

      <div role="tablist" aria-label="프로젝트 보기" className={s.tabs}>
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => pick(t)} className={s.tab}>
            {label[t]}
          </button>
        ))}
      </div>

      {!p.exists ? (
        <div className={s.notice}>폴더가 없어요: {p.root} — 옮겼다면 등록을 해제하고 새 경로로 다시 등록해 주세요.</div>
      ) : tab === 'files' ? (
        <FilesTab project={p} trees={trees.data} />
      ) : tab === 'worktrees' ? (
        <WorktreesTab project={p} trees={trees} />
      ) : tab === 'work' ? (
        <RunsTab project={p} trees={trees.data} />
      ) : (
        <SettingsTab project={p} />
      )}
    </>
  )
}
