import clsx from 'clsx'
import type { ReactNode } from 'react'
import type { Commit, FileNode, RunPayload } from '@/api/types'
import {
  Button,
  IconButton,
  LoadingState,
  ProgressBar,
  VisuallyHidden,
} from '@/components'
import { PanelIcon, Resizer } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { FileTree } from './FileTree'
import type { TreeTarget } from './TreeContextMenu'
import s from './SidePanels.module.css'

function PanelHead({
  title,
  caption,
  actions,
  onCollapse,
}: {
  title: string
  caption?: string
  actions?: ReactNode
  onCollapse?: () => void
}) {
  return (
    <div className={s.head}>
      <span className={s.title}>{title}</span>
      {caption && <span className={s.caption}>{caption}</span>}
      <div className={s.actions}>
        {actions}
        {/* 접기 버튼도 같은 줄에 둬야 다른 아이콘과 높이가 맞아요 */}
        {onCollapse && (
          <IconButton label="사이드바 접기" aria-expanded size={28} onClick={onCollapse}>
            <PanelIcon side="left" />
          </IconButton>
        )}
      </div>
    </div>
  )
}

/* ── 탐색기 ───────────────────────────────────────────────── */

interface ExplorerProps {
  tree: FileNode | undefined
  activeFileId: string | null
  onOpenFile: (id: string) => void
  creating: 'file' | 'folder' | null
  onStartCreate: (kind: 'file' | 'folder') => void
  onCreate: (name: string, kind: 'file' | 'folder') => void
  onCancelCreate: () => void
  created: Array<{ name: string; kind: 'file' | 'folder' }>
  collapseSignal: number
  onCollapseAll: () => void
  onRefresh: () => void
  onCollapse: () => void
  /** 탐색기 오른쪽 클릭 */
  onContextMenu: (target: TreeTarget, at: { x: number; y: number }) => void
  renaming: string | null
  onRename: (path: string, name: string) => void
  onCancelRename: () => void
  createAt: string | null
  onShortcut: (action: 'rename' | 'delete' | 'cut' | 'copy' | 'paste', target: TreeTarget) => void
}

export function ExplorerPanel({
  tree,
  activeFileId,
  onOpenFile,
  creating,
  onStartCreate,
  onCreate,
  onCancelCreate,
  created,
  collapseSignal,
  onCollapseAll,
  onRefresh,
  onCollapse,
  onContextMenu,
  renaming,
  onRename,
  onCancelRename,
  createAt,
  onShortcut,
}: ExplorerProps) {
  return (
    <div className={s.panel}>
      <PanelHead
        title="탐색기"
        onCollapse={onCollapse}
        actions={
          <>
            <IconButton label="새 파일" size={28} onClick={() => onStartCreate('file')}>
              <FileIcon />
            </IconButton>
            <IconButton label="새 폴더" size={28} onClick={() => onStartCreate('folder')}>
              <FolderIcon />
            </IconButton>
            <IconButton label="탐색기 새로 고침" size={28} onClick={onRefresh}>
              <RefreshIcon />
            </IconButton>
            <IconButton label="모두 접기" size={28} onClick={onCollapseAll}>
              <CollapseIcon />
            </IconButton>
          </>
        }
      />
      {tree ? (
        <FileTree
          root={tree}
          activeFileId={activeFileId}
          onOpenFile={onOpenFile}
          creating={creating}
          onCreate={onCreate}
          onCancelCreate={onCancelCreate}
          created={created}
          collapseSignal={collapseSignal}
          onContextMenu={onContextMenu}
          renaming={renaming}
          onRename={onRename}
          onCancelRename={onCancelRename}
          createAt={createAt}
          onShortcut={onShortcut}
        />
      ) : (
        <LoadingState label="파일 목록을 불러오는 중이에요…" />
      )}
    </div>
  )
}

/* ── 검색 ─────────────────────────────────────────────────── */

export function SearchPanel({ onCollapse }: { onCollapse: () => void }) {
  return (
    <div className={s.panel}>
      <PanelHead title="검색" onCollapse={onCollapse} />
      <div className={s.body}>
        <VisuallyHidden>
          <label htmlFor="code-find">프로젝트에서 검색</label>
        </VisuallyHidden>
        <input id="code-find" placeholder="프로젝트에서 검색" className={s.input} />
        <span className={s.hint}>파일 이름과 내용을 함께 검색해요</span>
      </div>
    </div>
  )
}

/* ── 소스 제어 ────────────────────────────────────────────── */

export function SourceControlPanel({
  run,
  commits,
  onCollapse,
}: {
  run: RunPayload | undefined
  commits: Commit[] | undefined
  onCollapse: () => void
}) {
  const sc = run?.sourceControl
  // VS Code 처럼 그래프 영역 높이를 끌어서 바꿔요
  const graph = usePaneResize({
    initial: 220,
    min: 80,
    max: 520,
    dir: -1,
    orientation: 'horizontal',
  })

  return (
    <div className={s.panel}>
      <PanelHead
        title="소스 제어"
        caption={sc ? `${sc.branch} · ${sc.ahead}` : undefined}
        onCollapse={onCollapse}
      />

      {sc && (
        <div className={s.block}>
          <VisuallyHidden>
            <label htmlFor="commit-msg">커밋 메시지</label>
          </VisuallyHidden>
          <input
            id="commit-msg"
            placeholder={sc.commitPlaceholder}
            className={s.input}
          />
          <div className={s.btnRow}>
            <Button variant="accent" size="sm">
              ✓ 커밋
            </Button>
            <Button size="sm">PR 열기</Button>
          </div>
        </div>
      )}

      {sc && (
        <>
          <span className={s.subTitle}>변경 내용 · {sc.changes.length}</span>
          <div className={s.changeList}>
            {sc.changes.map((c) => (
              <div key={c.path} className={s.changeRow}>
                <span className={s.changePath}>{c.path}</span>
                <span className={s.status}>{c.status}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <Resizer handle={graph.resizerProps} label="그래프 높이 조절" />

      <span className={s.subTitle}>그래프</span>
      <div style={graph.style} className={s.graphList}>
        {commits?.map((c, i) => (
        <div key={c.sha} className={s.commitRow}>
          <svg width="14" height="34" aria-hidden="true" className={s.graph}>
            <line
              x1="7"
              y1="0"
              x2="7"
              y2={i === (commits.length ?? 0) - 1 ? 20 : 34}
              stroke="currentColor"
              strokeWidth="2"
            />
            <circle
              cx="7"
              cy="17"
              r={i === 0 ? 5 : 4}
              fill={i === 0 ? 'var(--bg)' : 'var(--text-muted)'}
              stroke={i === 0 ? 'var(--accent)' : 'none'}
              strokeWidth="2"
            />
          </svg>
          <span className={s.commitMsg}>{c.msg}</span>
          <span className={s.commitMeta}>
            {c.author && <span className={s.aiTag}>{c.author} · </span>}
            {c.sha} · {c.branch}
          </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── 실험 실행 ────────────────────────────────────────────── */

export function RunPanel({
  run,
  onCollapse,
}: {
  run: RunPayload | undefined
  onCollapse: () => void
}) {
  if (!run) return <LoadingState label="실행 정보를 불러오는 중이에요…" />
  const { draft } = run

  return (
    <div className={s.panel}>
      <PanelHead title="실험 실행" caption={run.caption} onCollapse={onCollapse} />

      <div className={s.block}>
        <span className={s.title}>새 실험</span>
        <div className={s.grid}>
          <span className={s.gridLabel}>이름</span>
          <span className={s.gridValue}>{draft.name}</span>
          <span className={s.gridLabel}>기준</span>
          <span className={s.gridValue}>{draft.base}</span>
          <span className={s.gridLabel}>바뀐 파일</span>
          <span className={s.gridValue}>{draft.changed}</span>
          <span className={s.gridLabel}>환경</span>
          <Button size="sm">{draft.env} ▾</Button>
        </div>

        {draft.autoCommit && <Check label="실행 전 자동 커밋" />}
        {draft.newBranch && <Check label={`새 브랜치 ${draft.newBranchName} 생성`} />}

        <Button variant="accent" size="sm" fullWidth>
          큐에 추가
        </Button>
        <span className={s.hint}>{draft.hint}</span>
      </div>

      <span className={s.subTitle}>작업 큐</span>
      {run.queue.map((q) => (
        <div key={q.id} className={s.queueRow}>
          <div className={s.queueHead}>
            <span aria-hidden="true">●</span>
            <span className={s.queueId}>{q.id}</span>
            <span className={s.queueState}>{q.state}</span>
            {q.stoppable ? (
              <IconButton label={`${q.id} 정지`} size={26} variant="outline" className={s.spacer}>
                <StopIcon />
              </IconButton>
            ) : (
              <span aria-hidden="true" className={clsx(s.spacer, s.grip)}>
                ⋮⋮
              </span>
            )}
          </div>
          {q.progress !== null && <ProgressBar value={q.progress} height={4} rounded />}
          {q.detail && <span className={s.queueDetail}>{q.detail}</span>}
        </div>
      ))}

      <span className={s.subTitle}>최근 실행</span>
      {run.recent.map((r) => (
        <div key={r.id} className={s.recentRow}>
          <span className={s.recentId}>{r.id}</span>
          <span className={clsx(s.recentId, r.failed && s.failed)}>{r.result}</span>
          <a href={`#log-${r.id}`} className={s.spacer}>
            로그
          </a>
        </div>
      ))}
    </div>
  )
}

function Check({ label }: { label: string }) {
  return (
    <span className={s.check}>
      <span aria-hidden="true" className={s.checkBox}>
        ✓
      </span>
      {label}
    </span>
  )
}

/* ── 아이콘 ───────────────────────────────────────────────── */

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

const FileIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z" />
    <path d="M14 3v5h5M12 11v6M9 14h6" />
  </svg>
)
const FolderIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
    <path d="M12 11v4M10 13h4" />
  </svg>
)
const RefreshIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M21 12a9 9 0 11-3-6.7L21 8" />
    <path d="M21 3v5h-5" />
  </svg>
)
const CollapseIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M4 9h16M4 15h16M9 4l3 3 3-3M9 20l3-3 3 3" />
  </svg>
)
const StopIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
  </svg>
)
