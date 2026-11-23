import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Editor, loader, useMonaco } from '@monaco-editor/react'
import * as monacoEditor from 'monaco-editor'
import type { editor } from 'monaco-editor'
import '@/styles/monaco-worker'
import { EDITOR_OPTIONS, LAB_THEME, labTheme, languageLabel, languageOf } from '@/styles/monaco-theme'
import { gitDiffQuery, gitStatusQuery, projectQuery, worktreesQuery } from '@/api/projects'
import { fileContentQuery, fileOriginQuery, terminalsQuery, useGitAction, useSaveFile, useTerminalActions } from '@/api/ide'
import { sessionsQuery } from '@/api/agents'
import { ApiError } from '@/api/client'
import { Dialog, ErrorState, LoadingState, Resizer } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { agoShort } from '@/lib/time'
import { useIsMobile } from '@/lib/useMediaQuery'
import { FilesIcon, GearIcon, PlusIcon, GitIcon, HistoryIcon, NewSessionIcon, RunIcon, ScenarioIcon, SearchIcon } from '@/components/icons'
import { ChatPanel } from '../agents/ChatPanel'
import { NewSession } from '../agents/AdePage'
import { Explorer, GitPanel, RunPanel, SearchPanel } from './IdePanels'
import { TerminalView } from './TerminalView'
import { ScenarioView } from '../scenario/ScenarioView'
import s from './Ide.module.css'

// CDN 대신 번들의 monaco를 써요 (원격에서 바깥 네트워크에 기대지 않게)
loader.config({ monaco: monacoEditor })

/** IDE — docs/v3/mockups/IDE.dc.html */
type Side = 'explorer' | 'search' | 'git' | 'scenario' | 'run'
type Tab = { kind: 'file'; path: string } | { kind: 'diff'; path: string }
type Term = { kind: 'shell'; name: string } | { kind: 'run'; run: string }

const tabKey = (t: Tab) => `${t.kind}:${t.path}`
const termKey = (t: Term) => (t.kind === 'shell' ? `s:${t.name}` : `r:${t.run}`)

export default function IdePage() {
  const { id: project = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tree = params.get('tree') ?? ''
  const detail = useQuery(projectQuery(project))
  const trees = useQuery(worktreesQuery(project))
  const status = useQuery(gitStatusQuery(project, tree))
  const sessions = useQuery(sessionsQuery(project))
  const terms = useQuery(terminalsQuery(project))
  const termActions = useTerminalActions(project)

  // ADE의 Scenario에서 "실행 탭에 채우기"로 오면 ?side=run&fill=<명령>
  const [side, setSide] = useState<Side>((params.get('side') as Side) || 'explorer')
  // 목업처럼 지금 열린 아이콘을 다시 누르면 사이드바를 접어요
  const [sideOpen, setSideOpen] = useState(true)
  const mobile = useIsMobile()
  // 목업의 패널 너비 조절 — 끌거나 경계선에 초점을 두고 ←→
  const sidePane = usePaneResize({ initial: 270, min: 200, max: 560, dir: 1 })
  const chatPane = usePaneResize({ initial: 380, min: 300, max: 760, dir: -1 })
  const [freshChat, setFreshChat] = useState(false)
  const pickSide = (k: Side) => {
    if (k === side) setSideOpen((v) => !v)
    else {
      setSide(k)
      setSideOpen(true)
    }
  }
  const [fill, setFill] = useState<{ command: string; n: number } | null>(params.get('fill') ? { command: params.get('fill') as string, n: 1 } : null)
  const [tabs, setTabs] = useState<Tab[]>([])
  const [active, setActive] = useState('')
  const [jump, setJump] = useState<{ path: string; line: number } | null>(null)
  const [cursor, setCursor] = useState<{ line: number; column: number } | null>(null)
  const [dirty, setDirty] = useState<Record<string, boolean>>({})
  const [openTerms, setOpenTerms] = useState<Term[]>([])
  const [termActive, setTermActive] = useState('')
  const [bottomOpen, setBottomOpen] = useState(true)

  // 주소에 path가 있으면 그 파일을 열어요 (Projects의 "열기")
  useEffect(() => {
    const p = params.get('path')
    if (p) openFile(p)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 이미 있는 tmux 터미널은 탭으로 다시 붙어요
  useEffect(() => {
    const list = terms.data?.terminals ?? []
    setOpenTerms((old) => {
      const known = new Set(old.map(termKey))
      const add = list.filter((t) => !known.has(`s:${t.name}`)).map((t) => ({ kind: 'shell' as const, name: t.name }))
      return add.length ? [...old, ...add] : old
    })
  }, [terms.data])
  useEffect(() => {
    if (!termActive && openTerms[0]) setTermActive(termKey(openTerms[0]))
  }, [openTerms, termActive])

  const openFile = useCallback((path: string, line?: number) => {
    const t: Tab = { kind: 'file', path }
    setTabs((old) => (old.some((x) => tabKey(x) === tabKey(t)) ? old : [...old, t]))
    setActive(tabKey(t))
    if (line) setJump({ path, line })
  }, [])
  const openDiff = (path: string) => {
    const t: Tab = { kind: 'diff', path }
    setTabs((old) => (old.some((x) => tabKey(x) === tabKey(t)) ? old : [...old, t]))
    setActive(tabKey(t))
  }
  const closeTab = (key: string) => {
    if (dirty[key] && !window.confirm('저장하지 않은 변경이 있어요. 닫을까요?')) return
    setTabs((old) => {
      const next = old.filter((x) => tabKey(x) !== key)
      if (active === key) setActive(next.length ? tabKey(next[next.length - 1]) : '')
      return next
    })
  }
  const pickTree = (rel: string) => {
    const next = new URLSearchParams(params)
    if (rel) next.set('tree', rel)
    else next.delete('tree')
    next.delete('path')
    setParams(next, { replace: true })
    setTabs([])
    setActive('')
  }
  const newTerminal = () =>
    termActions.create.mutate(tree, {
      onSuccess: (t) => {
        const term: Term = { kind: 'shell', name: t.name }
        setOpenTerms((old) => [...old, term])
        setTermActive(termKey(term))
        setBottomOpen(true)
      },
    })
  // ADE의 "터미널로 열기" — ?term=new로 들어오면 그 위치에 새 터미널을 한 번 열어요
  const wantTerm = useRef(params.get('term') === 'new')
  useEffect(() => {
    if (!wantTerm.current) return
    wantTerm.current = false
    newTerminal()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const attachRun = (run: string) => {
    const term: Term = { kind: 'run', run }
    setOpenTerms((old) => (old.some((x) => termKey(x) === termKey(term)) ? old : [...old, term]))
    setTermActive(termKey(term))
    setBottomOpen(true)
  }
  const closeTerm = (t: Term) => {
    if (t.kind === 'shell') {
      if (!window.confirm(`${t.name} 터미널을 닫을까요? 그 안에서 돌던 것도 같이 끝나요.`)) return
      termActions.kill.mutate(t.name)
    }
    setOpenTerms((old) => old.filter((x) => termKey(x) !== termKey(t)))
    if (termActive === termKey(t)) setTermActive('')
  }

  const options = trees.data?.state === 'ok' ? trees.data.worktrees.filter((w) => w.rel !== null) : []
  const branch = status.data?.state === 'ok' ? status.data.branch : ''
  const treeLabel = `${project} · ${branch || (tree || '프로젝트 루트')}`
  // 이 worktree의 가장 최근 세션을 오른쪽 채팅에 (IDE ⇄ ADE가 같은 세션을 봐요)
  const chat = useMemo(
    () => (sessions.data?.sessions ?? []).find((x) => (x.tree === '.' ? '' : x.tree) === tree),
    [sessions.data, tree],
  )
  const activeTab = tabs.find((t) => tabKey(t) === active)

  if (mobile) {
    return (
      <main style={{ padding: '28px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>IDE는 넓은 화면에서 써요</h1>
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: 'var(--text-soft)' }}>
          편집기 · 터미널은 휴대폰 화면에 맞지 않아요. 에이전트에게 시키고 답하는 건 ADE에서 돼요.
        </p>
        <Link to={`/projects/${encodeURIComponent(project)}/ade${tree ? `?tree=${encodeURIComponent(tree)}` : ''}`} style={{ fontSize: 14 }}>
          ADE로 가기
        </Link>
      </main>
    )
  }
  if (detail.isPending) return <LoadingState label="프로젝트를 불러오는 중이에요" />
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />

  return (
    <div className={s.ide}>
      {/* WorkspaceBar — 프로젝트 › 브랜치 › IDE | ADE (같은 worktree를 들고 가요) */}
      <div className={s.bar}>
        <Link to={`/projects/${encodeURIComponent(project)}`} className={s.barProject}>
          ‹ {project}
        </Link>
        <label className={s.srOnly} htmlFor="ide-tree">
          브랜치 · worktree
        </label>
        <select id="ide-tree" className={s.barSelect} value={tree} onChange={(e) => pickTree(e.target.value)}>
          {options.length === 0 && <option value="">⎇ {branch || '프로젝트 루트'}</option>}
          {options.map((w) => (
            <option key={w.path} value={w.rel === '.' ? '' : (w.rel ?? '')}>
              ⎇ {w.branch || w.head}
              {w.rel && w.rel !== '.' ? ` · ${w.rel}` : ''}
            </option>
          ))}
        </select>
        <div role="group" aria-label="작업 화면 전환" className={s.switch}>
          <Link to="#" aria-current="page">
            IDE
          </Link>
          <Link to={`/projects/${encodeURIComponent(project)}/ade?${chat ? `session=${chat.id}` : `tree=${encodeURIComponent(tree)}`}`}>ADE</Link>
        </div>
      </div>

      <div className={s.body}>
        <nav aria-label="작업 표시줄" className={s.rail}>
          {(
            [
              ['explorer', '탐색기', <FilesIcon />],
              ['search', '검색', <SearchIcon size={22} weight={1.7} />],
              ['git', `소스 제어, 변경 ${status.data?.state === 'ok' ? status.data.changed : 0}개`, <GitIcon />],
              ['scenario', 'Scenario', <ScenarioIcon />],
              ['run', '실행', <RunIcon />],
            ] as [Side, string, ReactNode][]
          ).map(([k, label, icon]) => (
            <button key={k} type="button" aria-label={label} title={label} aria-pressed={side === k && sideOpen} className={s.railBtn} onClick={() => pickSide(k)}>
              {icon}
              {k === 'git' && status.data?.state === 'ok' && status.data.changed > 0 && <span className={s.railBadge}>{status.data.changed}</span>}
            </button>
          ))}
          <Link to={`/projects/${encodeURIComponent(project)}?tab=settings`} aria-label="설정" title="프로젝트 설정" className={`${s.railBtn} ${s.railBottom}`}>
            <GearIcon />
          </Link>
        </nav>

        <aside aria-label="사이드바" className={s.sidebar} hidden={!sideOpen} style={sidePane.style}>
          {side === 'explorer' && <Explorer key={tree} project={project} tree={tree} label={treeLabel} onOpen={openFile} />}
          {side === 'search' && <SearchPanel project={project} tree={tree} onOpen={openFile} />}
          {side === 'git' && <GitPanel project={project} tree={tree} onDiff={openDiff} />}
          {side === 'scenario' && (
            <ScenarioView
              project={project}
              onFill={(cmd) => {
                setFill({ command: cmd, n: (fill?.n ?? 0) + 1 })
                setSide('run')
              }}
            />
          )}
          {side === 'run' && (
            <RunPanel key={fill?.n ?? 0} project={project} detail={detail.data} tree={tree} branch={branch} onAttach={attachRun} fill={fill?.command} />
          )}
        </aside>

        {sideOpen && <Resizer handle={sidePane.resizerProps} label="사이드바 너비 조절" />}

        <div className={s.center}>
          <section aria-label="편집기" className={s.editorArea}>
            <div role="tablist" aria-label="열린 파일" className={s.tabs}>
              {tabs.map((t) => (
                <div key={tabKey(t)} className={s.tab} data-active={tabKey(t) === active}>
                  <button type="button" role="tab" aria-selected={tabKey(t) === active} className={s.tabBtn} onClick={() => setActive(tabKey(t))}>
                    {dirty[tabKey(t)] && <span className={s.dirty} aria-label="저장 안 함">●</span>}
                    {t.kind === 'diff' ? '변경 · ' : ''}
                    {t.path.split('/').pop()}
                  </button>
                  <button type="button" aria-label={`${t.path} 닫기`} className={s.tabClose} onClick={() => closeTab(tabKey(t))}>
                    ×
                  </button>
                </div>
              ))}
            </div>
            {activeTab ? (
              activeTab.kind === 'file' ? (
                <FileEditor
                  key={tabKey(activeTab)}
                  project={project}
                  tree={tree}
                  path={activeTab.path}
                  jumpLine={jump?.path === activeTab.path ? jump.line : undefined}
                  onCursor={setCursor}
                  onDirty={(d) => setDirty((old) => ({ ...old, [tabKey(activeTab)]: d }))}
                  onDiff={() => openDiff(activeTab.path)}
                />
              ) : (
                <DiffTab project={project} tree={tree} path={activeTab.path} onOpen={() => openFile(activeTab.path)} />
              )
            ) : (
              <div className={s.empty}>
                탐색기에서 파일을 누르면 여기서 열려요. <kbd>Ctrl</kbd>+<kbd>S</kbd> 로 저장해요.
              </div>
            )}
          </section>

          <section aria-label="터미널" className={s.bottom} data-open={bottomOpen}>
            <div className={s.termTabs}>
              <button type="button" className={s.termToggle} aria-expanded={bottomOpen} onClick={() => setBottomOpen(!bottomOpen)}>
                터미널 {bottomOpen ? '▾' : '▴'}
              </button>
              {openTerms.map((t) => (
                <div key={termKey(t)} className={s.tab} data-active={termKey(t) === termActive}>
                  <button type="button" className={s.tabBtn} onClick={() => setTermActive(termKey(t))}>
                    {t.kind === 'shell' ? `bash · ${t.name}` : `학습 · ${t.run}`}
                  </button>
                  <button type="button" aria-label="터미널 닫기" className={s.tabClose} onClick={() => closeTerm(t)}>
                    ×
                  </button>
                </div>
              ))}
              <button type="button" className={s.termNew} disabled={termActions.create.isPending} onClick={newTerminal} aria-label="새 터미널" title="새 터미널">
                <PlusIcon size={18} />
              </button>
              {termActions.create.error && <span className={s.errText}>{termActions.create.error instanceof ApiError ? termActions.create.error.message : ''}</span>}
            </div>
            {bottomOpen && (
              <div className={s.termBody}>
                {openTerms.length === 0 && <div className={s.empty}>+를 누르면 bash가 열려요. 브라우저를 닫아도 데스크톱에서 계속 돌아요.</div>}
                {openTerms.map((t) => (
                  <div key={termKey(t)} hidden={termKey(t) !== termActive} className={s.termPane}>
                    {t.kind === 'shell' ? <TerminalView project={project} name={t.name} /> : <TerminalView project={project} run={t.run} />}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <Resizer handle={chatPane.resizerProps} label="Claude Code 패널 너비 조절" />
        <aside aria-label="에이전트 채팅" className={s.chat} style={chatPane.style}>
          {chat && !freshChat ? (
            <ChatPanel
              key={chat.id}
              session={chat}
              actions={
                <>
                  <Link to={`/projects/${encodeURIComponent(project)}/ade?session=${encodeURIComponent(chat.id)}`} aria-label="세션 기록" title="세션 기록 (ADE)" className={s.chatIconBtn}>
                    <HistoryIcon />
                  </Link>
                  <button type="button" aria-label="새 세션" title="새 세션" className={s.chatIconBtn} onClick={() => setFreshChat(true)}>
                    <NewSessionIcon />
                  </button>
                </>
              }
            />
          ) : (
            sessions.isSuccess && <NewSession project={project} defaultTree={tree} onCancel={chat ? () => setFreshChat(false) : undefined} />
          )}
        </aside>
      </div>

      <footer className={s.status}>
        <span>⎇ {branch || '—'}</span>
        <span>변경 {status.data?.state === 'ok' ? status.data.changed : 0}</span>
        <span className={s.spacer} />
        {activeTab?.kind === 'file' && cursor && (
          <span>
            줄 {cursor.line}, 칸 {cursor.column}
          </span>
        )}
        {activeTab?.kind === 'file' && <span>{languageLabel(languageOf(activeTab.path))}</span>}
        <span>conda · {detail.data.settings.condaEnv || '없음'}</span>
        <span>터미널 {openTerms.length}</span>
      </footer>
    </div>
  )
}

function FileEditor({
  project,
  tree,
  path,
  jumpLine,
  onCursor,
  onDirty,
  onDiff,
}: {
  project: string
  tree: string
  path: string
  jumpLine?: number
  onCursor: (p: { line: number; column: number } | null) => void
  onDirty: (d: boolean) => void
  onDiff: () => void
}) {
  const file = useQuery(fileContentQuery(project, tree, path))
  // 출처 — 이 파일을 쓰거나 고친 에이전트 세션 · 커밋 안 한 변경인지
  const origin = useQuery(fileOriginQuery(project, tree, path))
  const status = useQuery(gitStatusQuery(project, tree))
  const change = status.data?.state === 'ok' ? status.data.changes.find((c) => c.path === path) : undefined
  const { discard } = useGitAction(project)
  const [asking, setAsking] = useState(false)
  const save = useSaveFile(project)
  const monaco = useMonaco()
  const ed = useRef<editor.IStandaloneCodeEditor | null>(null)
  const saved = useRef<string>('')
  const [err, setErr] = useState('')

  useEffect(() => {
    if (monaco) {
      monaco.editor.defineTheme(LAB_THEME, labTheme)
      monaco.editor.setTheme(LAB_THEME)
    }
  }, [monaco])
  useEffect(() => {
    if (file.data?.text != null) saved.current = file.data.text
  }, [file.data])
  useEffect(() => {
    if (jumpLine && ed.current) {
      ed.current.revealLineInCenter(jumpLine)
      ed.current.setPosition({ lineNumber: jumpLine, column: 1 })
      ed.current.focus()
    }
  }, [jumpLine])

  if (file.isPending) return <div className={s.empty}>불러오는 중이에요…</div>
  if (file.isError) return <div className={s.empty}>{file.error instanceof ApiError ? file.error.message : String(file.error)}</div>
  if (file.data.text === null) {
    return <div className={s.empty}>{file.data.reason === 'too-large' ? '파일이 커서(2 MB 넘음) 편집기로 열지 않아요. 내려받아서 봐 주세요.' : '글 파일이 아니라 열 수 없어요.'}</div>
  }

  const doSave = () => {
    const text = ed.current?.getValue() ?? ''
    save.mutate(
      { tree, path, text },
      {
        onSuccess: () => {
          saved.current = text
          onDirty(false)
          setErr('')
        },
        onError: (e) => setErr(e instanceof ApiError ? e.message : String(e)),
      },
    )
  }

  return (
    <div className={s.editorWrap}>
      <div className={s.crumb}>
        <span className={s.mono}>{path}</span>
        {origin.data?.origin && (
          <>
            <span className={s.muted}>
              Claude가 {agoShort(origin.data.origin.at)} 전에 {change?.label === 'U' || origin.data.origin.tool === 'Write' ? '만듦' : '고침'} · 세션 · {origin.data.origin.title}
            </span>
            <Link className={s.linkBtn} to={`/projects/${encodeURIComponent(project)}/ade?session=${encodeURIComponent(origin.data.origin.session)}`}>
              세션 보기
            </Link>
          </>
        )}
        {change && (
          <>
            <button type="button" className={s.linkBtn} onClick={onDiff}>
              변경 보기
            </button>
            <button type="button" className={s.linkBtn} onClick={() => setAsking(true)}>
              되돌리기…
            </button>
          </>
        )}
        {save.isPending && <span className={s.muted}>저장하는 중…</span>}
        {err && <span className={s.errText}>저장하지 못했어요: {err}</span>}
      </div>
      <Editor
        className={s.monaco}
        path={`${tree}/${path}`}
        defaultLanguage={languageOf(path)}
        defaultValue={file.data.text}
        theme={LAB_THEME}
        options={EDITOR_OPTIONS}
        loading={<div className={s.empty}>편집기를 불러오는 중이에요…</div>}
        onChange={(value) => onDirty((value ?? '') !== saved.current)}
        onMount={(instance, m) => {
          ed.current = instance
          instance.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, doSave)
          instance.onDidChangeCursorPosition((e) => onCursor({ line: e.position.lineNumber, column: e.position.column }))
          if (jumpLine) {
            instance.revealLineInCenter(jumpLine)
            instance.setPosition({ lineNumber: jumpLine, column: 1 })
          }
        }}
      />
      <Dialog
        open={asking}
        title={`${path}의 변경을 되돌릴까요?`}
        confirmLabel="되돌리기"
        busy={discard.isPending}
        error={discard.error ? (discard.error instanceof ApiError ? discard.error.message : String(discard.error)) : undefined}
        onClose={() => {
          discard.reset()
          setAsking(false)
        }}
        onConfirm={() =>
          discard.mutate(
            { tree, path },
            {
              onSuccess: async (r) => {
                setAsking(false)
                onDirty(false)
                // 편집기는 처음 값으로만 열려서, 되돌린 내용을 직접 넣어요
                const got = await file.refetch()
                if (!r.removed && got.data?.text != null) {
                  saved.current = got.data.text
                  ed.current?.setValue(got.data.text)
                }
              },
            },
          )
        }
      >
        <span>
          {change?.label === 'U' ? '새로 만든 파일이라 지워져요.' : '마지막 커밋 상태로 돌아가요.'} 되돌린 내용은 다시 살릴 수 없어요.
        </span>
      </Dialog>
    </div>
  )
}

function DiffTab({ project, tree, path, onOpen }: { project: string; tree: string; path: string; onOpen: () => void }) {
  const diff = useQuery(gitDiffQuery(project, tree, path))
  return (
    <div className={s.editorWrap}>
      <div className={s.crumb}>
        <span className={s.mono}>{path}</span>
        <span className={s.muted}>커밋 안 한 변경</span>
        <button type="button" className={s.linkBtn} onClick={onOpen}>
          편집기로 열기
        </button>
      </div>
      <pre className={s.diff}>
        {(diff.data?.diff || (diff.isPending ? '불러오는 중이에요…' : '바뀐 내용이 없거나 git이 아직 모르는 새 파일이에요.'))
          .split('\n')
          .map((line, i) => (
            <span key={i} data-sign={line.startsWith('+') && !line.startsWith('+++') ? '+' : line.startsWith('-') && !line.startsWith('---') ? '-' : line.startsWith('@@') ? '@' : ''}>
              {line}
              {'\n'}
            </span>
          ))}
      </pre>
    </div>
  )
}
