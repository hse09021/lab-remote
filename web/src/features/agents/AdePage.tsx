import { Fragment, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { closedSessionsQuery, sessionsQuery, useCloseSession, useCreateSession } from '@/api/agents'
import type { AgentSession, ModeId } from '@/api/agents'
import { dirQuery, gitDiffQuery, gitStatusQuery, projectQuery, worktreesQuery } from '@/api/projects'
import { runsQuery } from '@/api/runs'
import { ApiError } from '@/api/client'
import { ErrorState, LoadingState, Resizer } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { ChatIcon, FilesIcon, GearIcon, GitIcon, PlusIcon } from '@/components/icons'
import { agoShort } from '@/lib/time'
import { ChatPanel } from './ChatPanel'
import { Composer } from './Composer'
import type { ComposerSettings } from './Composer'
import { RunStatePill } from '../projects/RunsTab'
import { ScenarioView } from '../scenario/ScenarioView'
import { GitPanel } from '../ide/IdePanels'
import s from './Agents.module.css'

/** ADE — docs/v3/mockups/ADE.dc.html. 세션 목록 · 채팅 · Scenario/변경/실행 */
type Side = 'explorer' | 'git' | 'sessions'
type Right = 'scenario' | 'changes' | 'runs'

const treeParam = (t: string) => (t === '.' ? '' : t)

export default function AdePage() {
  const { id: project = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const sid = params.get('session') ?? ''
  const [side, setSide] = useState<Side>('sessions')
  const [sideOpen, setSideOpen] = useState(true)
  // IDE와 같은 패널 너비 조절
  const sidePane = usePaneResize({ initial: 280, min: 200, max: 560, dir: 1 })
  const rightPane = usePaneResize({ initial: 340, min: 260, max: 760, dir: -1 })
  const pickSide = (k: Side) => {
    if (k === side) setSideOpen((v) => !v)
    else {
      setSide(k)
      setSideOpen(true)
    }
  }
  const [right, setRight] = useState<Right>('changes')
  const [diffPath, setDiffPath] = useState('')
  const all = useQuery(sessionsQuery())
  const detail = useQuery(projectQuery(project))

  const sessions = all.data?.sessions ?? []
  const current = sessions.find((x) => x.id === sid)
  const tree = current ? treeParam(current.tree) : (params.get('tree') ?? '')
  const status = useQuery(gitStatusQuery(project, tree))
  const changes = status.data?.state === 'ok' ? status.data.changes : []
  const askCount = sessions.filter((x) => x.state === 'ask').length

  const navigate = useNavigate()
  const pick = (x: AgentSession) => {
    // 다른 프로젝트의 세션이면 그 프로젝트의 ADE로 가요
    navigate(`/projects/${encodeURIComponent(x.project)}/ade?session=${encodeURIComponent(x.id)}`)
    setDiffPath('')
  }
  const openDiff = (path: string) => {
    setDiffPath(path)
    setRight('changes')
  }

  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
  const branch = current?.branch || (detail.data?.git.state === 'ok' ? detail.data.git.branch : '')

  return (
    <div className={s.ade}>
      <div className={s.bar}>
        <Link to={`/projects/${encodeURIComponent(project)}`} className={s.barProject}>
          <span aria-hidden="true">‹</span>
          {project}
        </Link>
        {branch && <span className={s.barBranch}>⎇ {branch}</span>}
        <div role="group" aria-label="작업 화면 전환" className={s.switch}>
          {/* 같은 worktree를 들고 IDE로 */}
          <Link to={`/projects/${encodeURIComponent(project)}/ide${tree ? `?tree=${encodeURIComponent(tree)}` : ''}`}>IDE</Link>
          <Link to="#" aria-current="page">
            ADE
          </Link>
        </div>
      </div>

      <div className={s.adeBody}>
        <nav aria-label="작업 표시줄" className={s.rail}>
          <button type="button" aria-label="탐색기" title="탐색기" aria-pressed={side === 'explorer' && sideOpen} className={s.railBtn} onClick={() => pickSide('explorer')}>
            <FilesIcon />
          </button>
          <button type="button" aria-label={`소스 제어, 변경 ${changes.length}개`} title="소스 제어" aria-pressed={side === 'git' && sideOpen} className={s.railBtn} onClick={() => pickSide('git')}>
            <GitIcon />
            {changes.length > 0 && <span className={s.railBadge}>{changes.length}</span>}
          </button>
          <button type="button" aria-label={`세션, 답 필요 ${askCount}개`} title="세션" aria-pressed={side === 'sessions' && sideOpen} className={s.railBtn} onClick={() => pickSide('sessions')}>
            <ChatIcon />
            {askCount > 0 && <span className={s.railBadge} data-tone="ask">{askCount}</span>}
          </button>
          <Link to={`/projects/${encodeURIComponent(project)}?tab=settings`} aria-label="설정" title="프로젝트 설정" className={`${s.railBtn} ${s.railBottom}`}>
            <GearIcon />
          </Link>
        </nav>

        <aside aria-label="사이드바" className={s.sidebar} hidden={!sideOpen} style={sidePane.style}>
          {side === 'sessions' && (
            <SessionList
              sessions={sessions}
              current={sid}
              live={all.data?.live ?? 0}
              onPick={pick}
              onNew={() => setParams(new URLSearchParams({ new: '1' }))}
            />
          )}
          {side === 'explorer' && <Explorer project={project} tree={tree} branch={branch} onOpen={openDiff} />}
          {/* IDE와 같은 소스 제어 — 커밋 · PR · main에 합치기 */}
          {side === 'git' && <GitPanel project={project} tree={tree} onDiff={openDiff} />}
        </aside>
        {sideOpen && <Resizer handle={sidePane.resizerProps} label="사이드바 너비 조절" />}

        <main className={s.center}>
          {/* 휴대폰 — 옆 목록 대신 위에서 세션 고르기 */}
          <div className={s.mobileSessions}>
            <select
              aria-label="세션 고르기"
              value={current?.id ?? ''}
              onChange={(e) => {
                const x = sessions.find((y) => y.id === e.target.value)
                if (x) pick(x)
                else navigate(`/projects/${encodeURIComponent(project)}/ade`)
              }}
            >
              <option value="">+ 새 세션</option>
              {sessions.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.state === 'ask' ? '● ' : ''}
                  {x.project} · {x.title}
                </option>
              ))}
            </select>
          </div>
          {all.isPending && <LoadingState label="세션을 불러오는 중이에요" />}
          {all.isError && <ErrorState error={all.error} onRetry={() => all.refetch()} />}
          {current ? (
            <ChatPanel
              key={current.id}
              session={current}
              actions={
                <>
                  {/* 같은 위치(worktree)를 들고 IDE로 · 그 위치에 터미널을 열고 */}
                  <Link className={s.ghostBtn} to={`/projects/${encodeURIComponent(project)}/ide${tree ? `?tree=${encodeURIComponent(tree)}` : ''}`}>
                    IDE에서 열기
                  </Link>
                  <Link className={s.ghostBtn} to={`/projects/${encodeURIComponent(project)}/ide?${new URLSearchParams({ ...(tree ? { tree } : {}), term: 'new' })}`}>
                    터미널로 열기
                  </Link>
                </>
              }
            />
          ) : (
            all.isSuccess && <NewSession project={project} defaultTree={params.get('tree') ?? ''} draft={params.get('draft') ?? ''} />
          )}
        </main>

        <Resizer handle={rightPane.resizerProps} label="작업 정보 너비 조절" />
        <aside aria-label="작업 정보" className={s.rightPane} style={rightPane.style}>
          <div role="tablist" aria-label="작업 정보 보기" className={s.rtabs}>
            {(
              [
                ['scenario', 'Scenario'],
                ['changes', `변경 ${changes.length}`],
                ['runs', '실행'],
              ] as [Right, string][]
            ).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={right === k} className={s.rtab} onClick={() => setRight(k)}>
                {label}
              </button>
            ))}
          </div>
          <div className={s.rbody}>
            {right === 'scenario' && (
              <ScenarioView
                project={project}
                onFill={(cmd) =>
                  navigate(
                    `/projects/${encodeURIComponent(project)}/ide?${new URLSearchParams({ ...(tree ? { tree } : {}), side: 'run', fill: cmd })}`,
                  )
                }
              />
            )}
            {right === 'changes' && <Changes project={project} tree={tree} changes={changes} path={diffPath} onPick={setDiffPath} />}
            {right === 'runs' && <Runs project={project} />}
          </div>
        </aside>
      </div>
    </div>
  )
}

function SessionList({
  sessions,
  current,
  live,
  onPick,
  onNew,
}: {
  sessions: AgentSession[]
  current: string
  live: number
  onPick: (x: AgentSession) => void
  onNew: () => void
}) {
  const [mine, setMine] = useState(false)
  const [q, setQ] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const closed = useQuery(closedSessionsQuery(showClosed))
  const reopen = useCloseSession()
  const shown = sessions.filter(
    (x) => (!mine || x.state === 'ask') && (!q || `${x.title} ${x.branch} ${x.project}`.toLowerCase().includes(q.toLowerCase())),
  )
  const groups = useMemo(() => {
    const map = new Map<string, Map<string, AgentSession[]>>()
    for (const x of shown) {
      const p = map.get(x.project) ?? new Map<string, AgentSession[]>()
      const key = x.branch || (x.tree === '.' ? '프로젝트 루트' : x.tree)
      p.set(key, [...(p.get(key) ?? []), x])
      map.set(x.project, p)
    }
    return map
  }, [shown])
  const askN = sessions.filter((x) => x.state === 'ask').length

  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>세션</span>
        <span className={s.muted}>{sessions.length}</span>
        <button type="button" aria-label="새 세션" title="새 세션" className={s.iconBtn} onClick={onNew}>
          <PlusIcon />
        </button>
      </div>
      <div role="group" aria-label="세션 필터" className={s.seg}>
        <button type="button" aria-pressed={!mine} className={s.segBtn} onClick={() => setMine(false)}>
          전체 {sessions.length}
        </button>
        <button type="button" aria-pressed={mine} className={s.segBtn} onClick={() => setMine(true)}>
          내 차례 {askN}
        </button>
      </div>
      <label htmlFor="ade-find" className={s.srOnly}>
        세션 검색
      </label>
      <input id="ade-find" className={s.reason} placeholder="세션 · 브랜치 검색" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className={s.sessionGroups}>
        {[...groups.entries()].map(([proj, trees]) => (
          <div key={proj}>
            <div className={s.groupLabel}>{proj}</div>
            {[...trees.entries()].map(([branch, list]) => (
              <div key={branch} className={s.treeGroup}>
                <span className={s.treeLabel}>⎇ {branch}</span>
                {list.map((x) => (
                  <Fragment key={x.id}>
                  <button type="button" aria-current={x.id === current ? 'true' : undefined} className={s.sessionItem} onClick={() => onPick(x)}>
                    <span aria-hidden="true" className={s.dot} data-state={x.state} />
                    <span className={s.sessionText}>
                      <span className={s.sessionTitle}>{x.title}</span>
                      <span className={s.sessionSub} data-state={x.state}>
                        {x.state === 'ask' ? '답 필요' : x.todos?.current || x.stateLabel}
                      </span>
                    </span>
                    <span className={s.muted}>{agoShort(x.updatedAt)}</span>
                  </button>
                    {/* 하위 에이전트 — 일하는 중인 것만 (끝난 건 채팅 안에 남아요) */}
                    {(x.subagents ?? [])
                      .filter((t) => t.status === 'running')
                      .map((t) => (
                        <button key={t.taskId} type="button" className={s.subItem} onClick={() => onPick(x)} title={`${x.title}의 하위 에이전트`}>
                          <span aria-hidden="true" className={s.dot} data-state="working" />
                          <span className={s.sessionText}>
                            <span className={s.sessionTitle}>{t.description || '하위 에이전트'}</span>
                            <span className={s.sessionSub}>하위 에이전트 · 작업 중</span>
                          </span>
                        </button>
                      ))}
                  </Fragment>
                ))}
              </div>
            ))}
          </div>
        ))}
        {sessions.length === 0 && <div className={s.muted}>세션이 없어요. +를 눌러 시작해요.</div>}
        <button type="button" className={s.closedToggle} aria-expanded={showClosed} onClick={() => setShowClosed((v) => !v)}>
          {showClosed ? '▾' : '▸'} 닫은 세션{closed.data ? ` ${closed.data.length}` : ''}
        </button>
        {showClosed &&
          (closed.data ?? []).map((x) => (
            <div key={x.id} className={s.closedItem}>
              <span title={`${x.project} · ${x.branch}`}>{x.title}</span>
              <button
                type="button"
                className={s.ghostBtn}
                disabled={reopen.isPending}
                onClick={() => reopen.mutate({ sid: x.id, closed: false }, { onSuccess: () => onPick(x) })}
              >
                다시 열기
              </button>
            </div>
          ))}
        {showClosed && closed.data?.length === 0 && <div className={s.muted}>닫은 세션이 없어요.</div>}
      </div>
      <div className={s.panelFoot}>
        동시 세션 <b>{live}</b> / 4 · 브라우저를 닫아도 데스크톱에서 계속 돌아요.
      </div>
    </div>
  )
}

export function NewSession({
  project,
  defaultTree,
  draft = '',
  onCancel,
}: {
  project: string
  defaultTree: string
  draft?: string
  /** IDE에서 "새 세션"으로 열었을 때 — 원래 세션으로 돌아가기 */
  onCancel?: () => void
}) {
  const navigate = useNavigate()
  const create = useCreateSession()
  const trees = useQuery(worktreesQuery(project))
  const [where, setWhere] = useState(defaultTree || '.')
  const [branch, setBranch] = useState('')
  const [settings, setSettings] = useState<ComposerSettings>({ mode: 'manual' as ModeId, model: '', effort: '', ultracode: false })
  const options = trees.data?.state === 'ok' ? trees.data.worktrees.filter((w) => w.rel !== null) : []
  const err = create.error instanceof ApiError ? create.error.message : create.error ? String(create.error) : ''

  return (
    <section aria-label="새 세션" className={s.chat}>
      <div className={s.chatHead}>
        <span className={s.chatAgent}>새 세션 · Claude Code</span>
        {onCancel && (
          <button type="button" className={s.ghostBtn} onClick={onCancel}>
            돌아가기
          </button>
        )}
      </div>
      <div className={s.newForm}>
        <label className={s.field}>
          어디서 할까요
          <select className={s.reason} value={where} onChange={(e) => setWhere(e.target.value)}>
            {options.length === 0 && <option value=".">프로젝트 루트</option>}
            {options.map((w) => (
              <option key={w.path} value={w.rel ?? '.'}>
                {w.branch || w.head} · {w.rel === '.' ? '프로젝트 루트' : w.rel}
              </option>
            ))}
            <option value="__new">새 worktree 만들기…</option>
          </select>
        </label>
        {where === '__new' && (
          <label className={s.field}>
            새 브랜치 이름 (.labremote/worktrees/에 만들어요)
            <input className={s.reason} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="exp/early-stop" />
          </label>
        )}
        <p className={s.muted}>
          작업마다 worktree 하나씩 두면 세션끼리 파일이 섞이지 않아요. Mode · Model · Effort는 이 세션에만 적용되고 ~/.claude를 바꾸지
          않아요.
        </p>
      </div>
      <div className={s.messages} />
      {err && (
        <div role="alert" className={s.errBar}>
          {err}
        </div>
      )}
      <Composer
        settings={settings}
        onSettings={(next) => setSettings((old) => ({ ...old, ...next }))}
        busy={create.isPending}
        placeholder="첫 요청을 적으면 세션이 시작돼요"
        initialText={draft}
        onSend={(text) =>
          create.mutate(
            {
              project,
              text,
              tree: where === '__new' || where === '.' ? '' : where,
              newBranch: where === '__new' ? branch.trim() : '',
              ...settings,
            },
            { onSuccess: (made) => navigate(`/projects/${encodeURIComponent(project)}/ade?session=${made.id}`, { replace: true }) },
          )
        }
      />
    </section>
  )
}

function Explorer({ project, tree, branch, onOpen }: { project: string; tree: string; branch: string; onOpen: (p: string) => void }) {
  const [path, setPath] = useState('')
  const dir = useQuery(dirQuery(project, tree, path))
  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>탐색기</span>
      </div>
      <div className={s.muted}>
        {project} · {branch}
        {path && ` · ${path}`}
      </div>
      <ul className={s.fileList}>
        {path && (
          <li>
            <button type="button" className={s.fileBtn} onClick={() => setPath(path.split('/').slice(0, -1).join('/'))}>
              ‹ ..
            </button>
          </li>
        )}
        {dir.data?.entries.map((e) => (
          <li key={e.path}>
            <button
              type="button"
              className={s.fileBtn}
              disabled={e.outside}
              onClick={() => (e.kind === 'dir' ? setPath(e.path) : e.git && e.git !== 'gitignore' ? onOpen(e.path) : undefined)}
            >
              <span className={s.mono}>
                {e.kind === 'dir' ? '▸ ' : ''}
                {e.name}
              </span>
              {e.git && <span className={s.fileMark}>{e.git}</span>}
            </button>
          </li>
        ))}
      </ul>
      <div className={s.muted}>
        바뀐 파일을 누르면 오른쪽 변경 탭에 diff가 열려요. 직접 고치려면 <Link to={`/projects/${encodeURIComponent(project)}/ide`}>IDE에서 열어요</Link>.
      </div>
    </div>
  )
}

function Changes({
  project,
  tree,
  changes,
  path,
  onPick,
}: {
  project: string
  tree: string
  changes: { path: string; label: string }[]
  path: string
  onPick: (p: string) => void
}) {
  const diff = useQuery(gitDiffQuery(project, tree, path))
  return (
    <div className={s.changes}>
      {changes.length === 0 && <div className={s.muted}>커밋 안 한 변경이 없어요.</div>}
      {changes.map((c) => (
        <button key={c.path} type="button" aria-pressed={c.path === path} className={s.fileBtn} onClick={() => onPick(c.path)}>
          <span className={s.mono}>{c.path}</span>
          <span className={s.fileMark}>{c.label}</span>
        </button>
      ))}
      {path && (
        <pre className={s.codeBlock}>
          {diff.isPending
            ? '불러오는 중이에요…'
            : diff.data?.diff ||
              (changes.find((c) => c.path === path)?.label === '새 파일' ? 'git이 아직 추적하지 않는 새 파일이라 diff가 없어요.' : '바뀐 내용이 없어요.')}
        </pre>
      )}
    </div>
  )
}

function Runs({ project }: { project: string }) {
  const runs = useQuery(runsQuery(project))
  return (
    <div className={s.changes}>
      {runs.data?.runs.slice(0, 12).map((r) => (
        <Link key={r.id} to={`/projects/${encodeURIComponent(project)}?tab=work&run=${r.id}`} className={s.fileBtn}>
          <span className={s.mono}>{r.name ? `${r.id} · ${r.name}` : r.id}</span>
          <RunStatePill run={r} />
        </Link>
      ))}
      {runs.data?.runs.length === 0 && <div className={s.muted}>실행 기록이 없어요.</div>}
      <Link to={`/projects/${encodeURIComponent(project)}?tab=work`} className={s.ghostBtn}>
        새 실행 · 전체 보기
      </Link>
    </div>
  )
}
