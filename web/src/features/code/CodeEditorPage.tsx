import { useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  codeChatQuery,
  codeFilesQuery,
  commitsQuery,
  fileTreeQuery,
  permissionModesQuery,
  runQuery,
  terminalQuery,
  useCreateNode,
  useDeleteNode,
  useRenameNode,
} from '@/api/code'
import { CollapsedRail, ErrorState, LoadingState, Resizer } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { TerminalPanel, TerminalToolbar, useTerminals } from './TerminalPanel'
import { TreeContextMenu } from './TreeContextMenu'
import type { TreeAction, TreeTarget } from './TreeContextMenu'
import { copyText } from '@/lib/clipboard'
import { languageLabel, languageOf } from '@/styles/monaco-theme'
import { ChatPanel } from './ChatPanel'
import { EditorHost } from './EditorHost'
import { ExplorerPanel, RunPanel, SearchPanel, SourceControlPanel } from './SidePanels'
import s from './CodeEditorPage.module.css'

type SideId = 'explorer' | 'search' | 'git' | 'run'
type BottomTab = 'problems' | 'output' | 'terminal'

const SIDE_ITEMS: Array<{ id: SideId; label: string; badge?: string }> = [
  { id: 'explorer', label: '탐색기' },
  { id: 'search', label: '검색' },
  { id: 'git', label: '소스 제어', badge: '1' },
  { id: 'run', label: '실험 실행' },
]

export default function CodeEditorPage() {
  const side = usePaneResize({ initial: 270, min: 180, max: 480, dir: 1, collapsible: true })
  const chat = usePaneResize({ initial: 380, min: 280, max: 640, dir: -1, collapsible: true })
  const [maximized, setMaximized] = useState(false)
  const bottom = usePaneResize({
    initial: 230,
    min: 90,
    max: 560,
    dir: -1,
    orientation: 'horizontal',
    collapsible: true,
  })

  const [sideId, setSideId] = useState<SideId>('explorer')
  const [fileId, setFileId] = useState('config')
  const [bottomTab, setBottomTab] = useState<BottomTab>('terminal')
  const [cursor, setCursor] = useState<{ line: number; column: number } | null>(null)

  // 탐색기 인라인 생성
  const [creating, setCreating] = useState<'file' | 'folder' | null>(null)
  const [created, setCreated] = useState<Array<{ name: string; kind: 'file' | 'folder' }>>([])
  /** 탐색기 오른쪽 클릭 메뉴 */
  const [menu, setMenu] = useState<{ target: TreeTarget; at: { x: number; y: number } } | null>(
    null,
  )
  const [renaming, setRenaming] = useState<string | null>(null)
  /** 새로 만들 폴더의 전체 경로 */
  const [createAt, setCreateAt] = useState<string | null>(null)
  /** 잘라내기·복사해 둔 것 */
  const [clip, setClip] = useState<{ path: string; cut: boolean } | null>(null)
  /** 탐색기에서 "채팅에 추가" 한 것 */
  const [chatAttachment, setChatAttachment] = useState<string | null>(null)
  const [collapseSignal, setCollapseSignal] = useState(0)

  const [files, tree, terminal, commits, chatData, run] = useQueries({
    queries: [
      codeFilesQuery(),
      fileTreeQuery(),
      terminalQuery(),
      commitsQuery(),
      codeChatQuery(),
      runQuery(),
    ],
  })

  const terminals = useTerminals(terminal.data)
  const createNode = useCreateNode()
  const renameNode = useRenameNode()
  const deleteNode = useDeleteNode()
  const modes = useQuery(permissionModesQuery())

  const current = files.data?.find((f) => f.id === fileId) ?? files.data?.[0]

  /** 이미 열린 아이콘을 다시 누르면 사이드바가 접혀요 (VS Code와 같아요) */
  /** 오른쪽 클릭 메뉴에서 고른 것 */
  const onTreeAction = (action: TreeAction, t: TreeTarget) => {
    const parent = t.kind === 'file' ? t.path.split('/').slice(0, -1).join('/') : t.path
    // 루트 이름을 뺀 저장소 안 경로
    const relative = t.path.split('/').slice(1).join('/') || t.name

    switch (action) {
      case 'open':
        if (t.fileId) setFileId(t.fileId)
        break
      case 'newFile':
      case 'newFolder':
        setCreateAt(parent)
        setCreating(action === 'newFile' ? 'file' : 'folder')
        break
      case 'openInTerminal':
        setBottomTab('terminal')
        bottom.setOpen(true)
        terminals.add('bash')
        break
      case 'findInFolder':
        setSideId('search')
        break
      case 'addToChat':
        setChatAttachment(relative)
        break
      case 'cut':
      case 'copy':
        setClip({ path: t.path, cut: action === 'cut' })
        break
      case 'paste':
        if (clip) {
          const name = clip.path.split('/').pop() ?? ''
          createNode.mutate({ path: `${parent}/${name}`, kind: 'file' })
          if (clip.cut) deleteNode.mutate(clip.path)
          setClip(null)
        }
        break
      case 'copyPath':
        void copyText(`~/projects/${t.path}`)
        break
      case 'copyRelativePath':
        void copyText(relative)
        break
      case 'rename':
        setRenaming(t.path)
        break
      case 'delete':
        deleteNode.mutate(t.path)
        break
    }
  }

  const pickSide = (id: SideId) => {
    if (id === sideId) side.toggle()
    else {
      setSideId(id)
      side.setOpen(true)
    }
  }

  return (
    <main className={s.main}>
      <div className={s.frame}>
        <div className={s.shell}>
          <div className={s.body}>
            <nav aria-label="작업 표시줄" className={s.activityBar}>
              {SIDE_ITEMS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-label={item.label}
                  title={item.label}
                  aria-pressed={item.id === sideId && side.open}
                  onClick={() => pickSide(item.id)}
                  className={s.activityBtn}
                >
                  <SideIcon id={item.id} />
                  {item.badge && <span className={s.activityBadge}>{item.badge}</span>}
                </button>
              ))}
              <button
                type="button"
                aria-label="설정"
                title="설정"
                className={clsx(s.activityBtn, s.settingsBtn)}
              >
                <SideIcon id="settings" />
              </button>
            </nav>

            <aside aria-label="사이드바" style={side.style} className={s.sidebar}>
              {sideId === 'explorer' && (
                <ExplorerPanel
                  tree={tree.data}
                  activeFileId={current?.id ?? null}
                  onOpenFile={setFileId}
                  creating={creating}
                  onStartCreate={(kind) => {
                    setCreateAt(tree.data?.name ?? null)
                    setCreating(kind)
                  }}
                  onCreate={(name, kind) => {
                    if (createAt) {
                      createNode.mutate({
                        path: `${createAt}/${name}`,
                        kind: kind === 'folder' ? 'dir' : 'file',
                      })
                    } else {
                      setCreated((prev) => [...prev, { name, kind }])
                    }
                    setCreating(null)
                    setCreateAt(null)
                  }}
                  onCancelCreate={() => {
                    setCreating(null)
                    setCreateAt(null)
                  }}
                  created={created}
                  collapseSignal={collapseSignal}
                  onCollapseAll={() => {
                    setCollapseSignal((n) => n + 1)
                    setCreating(null)
                  }}
                  onRefresh={() => void tree.refetch()}
                  onCollapse={side.toggle}
                  onContextMenu={(target, at) => setMenu({ target, at })}
                  renaming={renaming}
                  onRename={(path, name) => {
                    renameNode.mutate({ path, name })
                    setRenaming(null)
                  }}
                  onCancelRename={() => setRenaming(null)}
                  createAt={createAt}
                  onShortcut={onTreeAction}
                />
              )}
              {sideId === 'search' && <SearchPanel onCollapse={side.toggle} />}
              {sideId === 'git' && (
                <SourceControlPanel
                  run={run.data}
                  commits={commits.data}
                  onCollapse={side.toggle}
                />
              )}
              {sideId === 'run' && <RunPanel run={run.data} onCollapse={side.toggle} />}
            </aside>

            {side.closed && (
              <CollapsedRail side="left" label="사이드바 펼치기" onExpand={side.toggle} />
            )}

            <Resizer handle={side.resizerProps} label="사이드바 너비 조절" />

            <div className={s.editorCol}>
              {/* 최대화해도 편집기를 떼지 않아요 — 떼면 Monaco 모델이 먼저 버려져요 */}
              <section
                aria-label="편집기"
                data-collapsed={maximized || undefined}
                className={s.editorSection}
              >
                <div role="tablist" aria-label="열린 파일" className={s.tabs}>
                  {files.data?.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      role="tab"
                      aria-selected={f.id === current?.id}
                      onClick={() => setFileId(f.id)}
                      className={s.tab}
                    >
                      {f.label}
                      <span aria-hidden="true">×</span>
                    </button>
                  ))}
                </div>

                <div className={s.crumb}>{current?.crumb ?? ''}</div>

                {files.isError ? (
                  <ErrorState
                    title="파일을 불러오지 못했어요"
                    error={files.error}
                    onRetry={() => void files.refetch()}
                  />
                ) : current ? (
                  <EditorHost key={current.id} file={current} onCursor={setCursor} />
                ) : (
                  <LoadingState label="파일을 불러오는 중이에요…" />
                )}
              </section>

              {bottom.closed ? (
                <button
                  type="button"
                  aria-label="하단 패널 펼치기"
                  onClick={bottom.toggle}
                  className={s.bottomRail}
                >
                  문제 · 출력 · 터미널
                </button>
              ) : (
                <Resizer handle={bottom.resizerProps} label="하단 패널 높이 조절" />
              )}

              <section
                aria-label="하단 패널"
                style={maximized ? { flex: '1 1 auto', minHeight: 0 } : bottom.style}
                className={s.bottom}
              >
                <div role="tablist" aria-label="하단 패널" className={s.panelTabs}>
                  <PanelTab
                    id="problems"
                    label="문제"
                    active={bottomTab}
                    onPick={setBottomTab}
                    count={terminal.data?.problems ?? 0}
                  />
                  <PanelTab id="output" label="출력" active={bottomTab} onPick={setBottomTab} />
                  <PanelTab
                    id="terminal"
                    label="터미널"
                    active={bottomTab}
                    onPick={setBottomTab}
                  />
                  {bottomTab === 'terminal' ? (
                    <TerminalToolbar
                      terminals={terminals}
                      maximized={maximized}
                      onToggleMaximize={() => setMaximized((v) => !v)}
                      onClose={bottom.toggle}
                    />
                  ) : (
                    terminal.data && (
                      <span className={s.panelSession}>{terminal.data.session}</span>
                    )
                  )}
                </div>

                {bottomTab === 'terminal' && (
                  <TerminalPanel data={terminal.data} terminals={terminals} />
                )}

                {bottomTab === 'problems' && (
                  <div className={s.panelEmpty}>
                    {terminal.data?.problems === 0
                      ? '문제가 없어요.'
                      : `문제 ${terminal.data?.problems ?? 0}개`}
                  </div>
                )}
                {bottomTab === 'output' && (
                  <div className={s.panelEmpty}>표시할 출력이 없어요.</div>
                )}
              </section>
            </div>

            <Resizer handle={chat.resizerProps} label="Claude Code 패널 너비 조절" />

            {chat.closed ? (
              <CollapsedRail
                side="right"
                label="Claude Code 패널 펼치기"
                onExpand={chat.toggle}
              />
            ) : (
              <ChatPanel
                style={chat.style}
                chat={chatData.data}
                modes={modes.data}
                fileLabel={current?.label ?? ''}
                attachment={chatAttachment}
                onRemoveAttachment={() => setChatAttachment(null)}
                onCollapse={chat.toggle}
              />
            )}
          </div>

          {menu && (
            <TreeContextMenu
              target={menu.target}
              at={menu.at}
              canPaste={!!clip}
              onPick={onTreeAction}
              onClose={() => setMenu(null)}
            />
          )}

          <footer className={s.statusBar}>
            <span>⎇ {run.data?.sourceControl.branch ?? '—'}</span>
            <span>✕ 0 ⚠ 0</span>
            <span className={s.statusRight}>
              {current?.readOnly
                ? '읽기 전용'
                : cursor
                  ? `줄 ${cursor.line}, 열 ${cursor.column}`
                  : '—'}
            </span>
            <span>공백: 2</span>
            <span>UTF-8</span>
            <span>LF</span>
            <span>{current ? languageLabel(languageOf(current.path)) : ''}</span>
            <span>● Claude Code</span>
          </footer>
        </div>
      </div>
    </main>
  )
}

function PanelTab({
  id,
  label,
  active,
  onPick,
  count,
}: {
  id: BottomTab
  label: string
  active: BottomTab
  onPick: (t: BottomTab) => void
  count?: number
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={id === active}
      onClick={() => onPick(id)}
      className={s.panelTab}
    >
      {label}
      {/* 알릴 게 있을 때만 숫자를 보여 줘요 (0 은 안 띄워요) */}
      {count !== undefined && count > 0 && <span className={s.countPill}>{count}</span>}
    </button>
  )
}

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

function SideIcon({ id }: { id: SideId | 'settings' }) {
  switch (id) {
    case 'explorer':
      return (
        <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
          <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
        </svg>
      )
    case 'search':
      return (
        <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
      )
    case 'git':
      return (
        <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="6" cy="18" r="2.5" />
          <circle cx="18" cy="12" r="2.5" />
          <path d="M6 8.5v7M8.5 6h4a3 3 0 013 3v.5" />
        </svg>
      )
    case 'run':
      // 실험 실행 — 삼각형(재생)보다 플라스크가 이 화면에 맞아요
      return (
        <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
          <path d="M10 3h4M10 3v6.2L4.8 18A2 2 0 006.5 21h11a2 2 0 001.7-3L14 9.2V3" />
          <path d="M7.5 15h9" />
        </svg>
      )
    case 'settings':
      return (
        <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 008 19.4a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H2a2 2 0 110-4h.1A1.7 1.7 0 003.6 8a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H8a1.7 1.7 0 001-1.5V2a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V8a1.7 1.7 0 001.5 1H22a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
        </svg>
      )
  }
}
