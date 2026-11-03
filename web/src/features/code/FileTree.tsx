import { useState } from 'react'
import clsx from 'clsx'
import type { KeyboardEvent } from 'react'
import type { FileNode } from '@/api/types'
import { VisuallyHidden } from '@/components'
import type { TreeTarget } from './TreeContextMenu'
import s from './FileTree.module.css'

/** 들여쓰기: 목업의 22 / 38 / 54px 와 같아요 */
const INDENT_BASE = 6
const INDENT_STEP = 16

export interface CreateRequest {
  kind: 'file' | 'folder'
  /** 만들어질 위치. 지금은 루트만 */
  parent: string
}

interface Props {
  root: FileNode
  /** 지금 편집기에 열려 있는 파일 */
  activeFileId: string | null
  onOpenFile: (fileId: string) => void
  /** 인라인 생성 중이면 종류, 아니면 null */
  creating: 'file' | 'folder' | null
  onCreate: (name: string, kind: 'file' | 'folder') => void
  onCancelCreate: () => void
  /** 사용자가 새로 만든 항목 (목업처럼 루트 바로 아래에 붙어요) */
  created: Array<{ name: string; kind: 'file' | 'folder' }>
  /** 모두 접기를 누를 때마다 올라가요 */
  collapseSignal: number
  /** 오른쪽 클릭 — 누른 자리와 대상을 넘겨요 */
  onContextMenu: (target: TreeTarget, at: { x: number; y: number }) => void
  /** 이름을 바꾸는 중인 전체 경로 */
  renaming: string | null
  onRename: (path: string, name: string) => void
  onCancelRename: () => void
  /** 인라인 생성이 일어날 폴더의 전체 경로 */
  createAt: string | null
  /** 행에 포커스를 두고 누르는 단축키 (F2 · Del · Ctrl+X/C/V) */
  onShortcut: (action: 'rename' | 'delete' | 'cut' | 'copy' | 'paste', target: TreeTarget) => void
}

export function FileTree(props: Props) {
  const { root, onContextMenu } = props
  return (
    <ul
      className={s.list}
      onContextMenu={(e) => {
        // 행이 아닌 빈 곳을 눌렀을 때예요
        if ((e.target as HTMLElement).closest(`.${s.row}`)) return
        e.preventDefault()
        onContextMenu(
          { kind: 'empty', path: root.name, name: root.name },
          { x: e.clientX, y: e.clientY },
        )
      }}
    >
      <TreeNode {...props} node={root} depth={0} path={root.name} isRoot />
    </ul>
  )
}

interface NodeProps extends Omit<Props, 'root'> {
  node: FileNode
  depth: number
  /** 루트부터 이어 붙인 전체 경로 */
  path: string
  isRoot?: boolean
}

function TreeNode({
  node,
  depth,
  path,
  activeFileId,
  onOpenFile,
  creating,
  onCreate,
  onCancelCreate,
  created,
  collapseSignal,
  onContextMenu,
  renaming,
  onRename,
  onCancelRename,
  createAt,
  onShortcut,
  isRoot = false,
}: NodeProps) {
  const [open, setOpen] = useState(node.open ?? false)
  const [lastSignal, setLastSignal] = useState(collapseSignal)

  // "모두 접기"를 누르면 모든 가지를 닫아요
  if (collapseSignal !== lastSignal) {
    setLastSignal(collapseSignal)
    if (open) setOpen(false)
  }

  const indent = INDENT_BASE + depth * INDENT_STEP
  const isDir = node.kind === 'dir'
  const active = node.fileId != null && node.fileId === activeFileId

  const target: TreeTarget = {
    kind: isDir ? 'dir' : 'file',
    path,
    name: node.name,
    fileId: node.fileId,
  }

  if (renaming === path) {
    return (
      <li>
        <NameRow
          indent={indent}
          initial={node.name}
          isDir={isDir}
          onCommit={(name) => onRename(path, name)}
          onCancel={onCancelRename}
        />
      </li>
    )
  }

  return (
    <li>
      <button
        type="button"
        aria-expanded={isDir ? open : undefined}
        aria-current={active ? 'true' : undefined}
        style={{ paddingLeft: indent }}
        className={clsx(s.row, isDir && s.dir, node.muted && s.muted)}
        onContextMenu={(e) => {
          e.preventDefault()
          e.stopPropagation()
          if (isDir && !open) setOpen(true)
          onContextMenu(target, { x: e.clientX, y: e.clientY })
        }}
        onKeyDown={(e) => {
          const key = e.key
          if (key === 'F2') {
            e.preventDefault()
            onShortcut('rename', target)
          } else if (key === 'Delete') {
            e.preventDefault()
            onShortcut('delete', target)
          } else if (e.ctrlKey && (key === 'x' || key === 'c' || key === 'v')) {
            e.preventDefault()
            onShortcut(key === 'x' ? 'cut' : key === 'c' ? 'copy' : 'paste', target)
          }
        }}
        onClick={() => {
          if (isDir) setOpen((v) => !v)
          else if (node.fileId) onOpenFile(node.fileId)
        }}
      >
        {isDir && (
          <span aria-hidden="true" className={s.caret}>
            {open ? '▾' : '▸'}
          </span>
        )}
        <span className={s.name}>
          {node.name}
          {isDir && !isRoot ? '/' : ''}
          {node.note && <span className={s.muted}> {node.note}</span>}
        </span>
        {node.lock && <span className={s.badge}>{node.lock}</span>}
        {node.gitStatus && (
          <span data-kind={node.gitStatus} className={s.badge}>
            {node.gitStatus}
          </span>
        )}
      </button>

      {isDir && open && (
        <ul>
          {creating && createAt === path && (
            <CreateRow
              kind={creating}
              indent={INDENT_BASE + (depth + 1) * INDENT_STEP}
              onCommit={onCreate}
              onCancel={onCancelCreate}
            />
          )}
          {isRoot &&
            created.map((c) => (
              <li key={`${c.kind}-${c.name}`}>
                <span
                  style={{ paddingLeft: INDENT_BASE + (depth + 1) * INDENT_STEP }}
                  className={clsx(s.row, c.kind === 'folder' && s.dir)}
                >
                  {c.kind === 'folder' && (
                    <span aria-hidden="true" className={s.caret}>
                      ▸
                    </span>
                  )}
                  <span className={s.name}>
                    {c.name}
                    {c.kind === 'folder' ? '/' : ''}
                  </span>
                  <span data-kind="U" className={s.badge}>
                    U
                  </span>
                </span>
              </li>
            ))}
          {(node.children ?? []).map((child) => (
            <TreeNode
              key={child.name}
              node={child}
              depth={depth + 1}
              path={`${path}/${child.name}`}
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
          ))}
        </ul>
      )}
    </li>
  )
}

function CreateRow({
  kind,
  indent,
  onCommit,
  onCancel,
}: {
  kind: 'file' | 'folder'
  indent: number
  onCommit: (name: string, kind: 'file' | 'folder') => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault()
      const trimmed = name.trim().replace(/\/+$/, '')
      if (trimmed) onCommit(trimmed, kind)
      else onCancel()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
    }
  }

  return (
    <li>
      <div style={{ paddingLeft: indent }} className={s.createRow}>
        {kind === 'folder' && (
          <span aria-hidden="true" className={s.caret}>
            ▸
          </span>
        )}
        <VisuallyHidden>
          <label htmlFor="tree-new">
            {kind === 'folder' ? '새 폴더 이름' : '새 파일 이름'}
          </label>
        </VisuallyHidden>
        <input
          id="tree-new"
          autoFocus
          value={name}
          placeholder={kind === 'folder' ? '폴더 이름' : '파일 이름'}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onCancel}
          className={s.createInput}
        />
      </div>
    </li>
  )
}

/** 이름 바꾸기 — 지금 이름이 들어간 채로 시작해요 */
function NameRow({
  indent,
  initial,
  isDir,
  onCommit,
  onCancel,
}: {
  indent: number
  initial: string
  isDir: boolean
  onCommit: (name: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial)

  return (
    <div style={{ paddingLeft: indent }} className={s.createRow}>
      {isDir && (
        <span aria-hidden="true" className={s.caret}>
          ▸
        </span>
      )}
      <VisuallyHidden>
        <label htmlFor="tree-rename">이름 바꾸기</label>
      </VisuallyHidden>
      <input
        id="tree-rename"
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            e.preventDefault()
            const trimmed = name.trim().replace(/\/+$/, '')
            if (trimmed && trimmed !== initial) onCommit(trimmed)
            else onCancel()
          } else if (e.key === 'Escape') {
            e.preventDefault()
            onCancel()
          }
        }}
        onBlur={onCancel}
        className={s.createInput}
      />
    </div>
  )
}
