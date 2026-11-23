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
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import { agoShort } from '@/lib/time'
import { FilesTab } from './FilesTab'
import { WorktreesTab } from './WorktreesTab'
import { SettingsTab } from './SettingsTab'
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
    if (!id && projects.length > 0) navigate(`/projects/${encodeURIComponent(projects[0].name)}`, { replace: true })
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
      {/* 상태 점: 답 필요/작업 중은 세션이 붙는 3단계부터 — 지금은 모두 쉼 */}
      <span aria-hidden="true" className={s.itemDot} data-tone="idle" />
      <span className={s.itemText}>
        <span className={s.itemName}>{p.name}</span>
        <span className={s.itemSub}>{p.exists ? gitLine(p.git) : '폴더가 없어요'}</span>
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
        폴더 안에 <span className={s.mono}>.labremote/</span> 를 만들어요. 스스로 git 에서 빠지고, 프로젝트의{' '}
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
            <span aria-hidden="true" className={s.bigDot} data-tone="idle" />
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
            <span className={s.chip} title="세션은 3단계에서 붙어요">
              세션 —
            </span>
            <span className={s.chip} title="실행 기록은 2단계에서 붙어요">
              실행 —
            </span>
          </div>
        </div>
        <Link to={`${base}/ide`} className={s.headLink}>
          IDE 에서 열기
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
        <div className={s.workGrid}>
          <section aria-label="세션" className={s.workCard}>
            <h2 className={s.h2}>세션</h2>
            <div className={s.muted}>에이전트 세션은 3단계(채팅)에서 붙어요.</div>
          </section>
          <section aria-label="실행" className={s.workCard}>
            <h2 className={s.h2}>실행</h2>
            <div className={s.muted}>실행 기록은 2단계(labremote run)에서 붙어요.</div>
          </section>
        </div>
      ) : (
        <SettingsTab project={p} />
      )}
    </>
  )
}
