import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import s from './TreeContextMenu.module.css'

/** 어디를 눌렀는지 — 메뉴 구성이 달라져요 */
export type TreeTargetKind = 'file' | 'dir' | 'empty'

export interface TreeTarget {
  kind: TreeTargetKind
  /** 루트를 포함한 전체 경로. 빈 곳이면 루트 경로 */
  path: string
  name: string
  /** 파일이면 편집기에서 열 id */
  fileId?: string
}

export type TreeAction =
  | 'open'
  | 'newFile'
  | 'newFolder'
  | 'openInTerminal'
  | 'findInFolder'
  | 'addToChat'
  | 'cut'
  | 'copy'
  | 'paste'
  | 'copyPath'
  | 'copyRelativePath'
  | 'rename'
  | 'delete'

interface Item {
  id: TreeAction
  label: string
  hint?: string
  disabled?: boolean
}

/** 구분선 */
const SEP = null
type Row = Item | typeof SEP

/**
 * 탐색기 오른쪽 클릭 메뉴. VS Code 의 묶음·순서를 따랐어요.
 * 이 프로젝트에 없는 것(공유·다운로드·작업 영역·타임라인)은 넣지 않았어요.
 */
function rowsFor(target: TreeTarget, canPaste: boolean): Row[] {
  if (target.kind === 'file') {
    return [
      { id: 'open', label: '편집기에서 열기', hint: 'Enter' },
      { id: 'openInTerminal', label: '통합 터미널에서 열기' },
      SEP,
      { id: 'addToChat', label: '채팅에 파일 추가' },
      SEP,
      { id: 'cut', label: '잘라내기', hint: 'Ctrl+X' },
      { id: 'copy', label: '복사', hint: 'Ctrl+C' },
      SEP,
      { id: 'copyPath', label: '경로 복사', hint: 'Shift+Alt+C' },
      { id: 'copyRelativePath', label: '상대 경로 복사', hint: 'Ctrl+K Ctrl+Shift+C' },
      SEP,
      { id: 'rename', label: '이름 바꾸기…', hint: 'F2' },
      { id: 'delete', label: '삭제', hint: 'Del' },
    ]
  }

  const folder: Row[] = [
    { id: 'newFile', label: '새 파일…' },
    { id: 'newFolder', label: '새 폴더…' },
    { id: 'openInTerminal', label: '통합 터미널에서 열기' },
    SEP,
    { id: 'findInFolder', label: '폴더에서 찾기…', hint: 'Shift+Alt+F' },
    SEP,
    { id: 'addToChat', label: '채팅에 폴더 추가' },
    SEP,
  ]

  if (target.kind === 'dir') {
    return [
      ...folder,
      { id: 'cut', label: '잘라내기', hint: 'Ctrl+X' },
      { id: 'copy', label: '복사', hint: 'Ctrl+C' },
      { id: 'paste', label: '붙여넣기', hint: 'Ctrl+V', disabled: !canPaste },
      SEP,
      { id: 'copyPath', label: '경로 복사', hint: 'Shift+Alt+C' },
      { id: 'copyRelativePath', label: '상대 경로 복사', hint: 'Ctrl+K Ctrl+Shift+C' },
      SEP,
      { id: 'rename', label: '이름 바꾸기…', hint: 'F2' },
      { id: 'delete', label: '삭제', hint: 'Del' },
    ]
  }

  // 빈 곳 — 지울 대상이 없어서 이름 바꾸기·삭제가 없어요
  return [
    ...folder,
    { id: 'paste', label: '붙여넣기', hint: 'Ctrl+V', disabled: !canPaste },
    SEP,
    { id: 'copyPath', label: '경로 복사', hint: 'Shift+Alt+C' },
    { id: 'copyRelativePath', label: '상대 경로 복사', hint: 'Ctrl+K Ctrl+Shift+C' },
  ]
}

interface Props {
  target: TreeTarget
  at: { x: number; y: number }
  canPaste: boolean
  onPick: (action: TreeAction, target: TreeTarget) => void
  onClose: () => void
}

export function TreeContextMenu({ target, at, canPaste, onPick, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState(at)
  const rows = rowsFor(target, canPaste)
  const items = rows.filter((r): r is Item => r !== SEP)
  const [cursor, setCursor] = useState(-1)

  /* 화면 밖으로 나가지 않게 자리를 잡아요 */
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setPos({
      x: Math.max(8, Math.min(at.x, window.innerWidth - r.width - 8)),
      y: Math.max(8, Math.min(at.y, window.innerHeight - r.height - 8)),
    })
  }, [at])

  useEffect(() => {
    ref.current?.focus()
    const onDown = (e: globalThis.PointerEvent) => {
      if (e.target instanceof Node && !ref.current?.contains(e.target)) onClose()
    }
    const onScroll = () => onClose()
    document.addEventListener('pointerdown', onDown)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      window.removeEventListener('resize', onScroll)
    }
  }, [onClose])

  const move = (step: number) => {
    const usable = items.filter((i) => !i.disabled)
    if (!usable.length) return
    const now = items[cursor]
    const at2 = now ? usable.findIndex((i) => i.id === now.id) : -1
    const next = usable[(at2 + step + usable.length) % usable.length]
    setCursor(items.findIndex((i) => i.id === next.id))
  }

  return createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label={`${target.name} 메뉴`}
      tabIndex={-1}
      style={{ left: pos.x, top: pos.y }}
      className={s.menu}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault()
          onClose()
        } else if (e.key === 'ArrowDown') {
          e.preventDefault()
          move(1)
        } else if (e.key === 'ArrowUp') {
          e.preventDefault()
          move(-1)
        } else if (e.key === 'Enter' && items[cursor] && !items[cursor].disabled) {
          e.preventDefault()
          onPick(items[cursor].id, target)
          onClose()
        }
      }}
    >
      {rows.map((row, i) =>
        row === SEP ? (
          <div key={`sep-${i}`} role="separator" className={s.sep} />
        ) : (
          <button
            key={row.id}
            type="button"
            role="menuitem"
            disabled={row.disabled}
            data-cursor={items[cursor]?.id === row.id ? 'true' : undefined}
            onClick={() => {
              onPick(row.id, target)
              onClose()
            }}
            className={s.item}
          >
            <span>{row.label}</span>
            {row.hint && <span className={s.hint}>{row.hint}</span>}
          </button>
        ),
      )}
    </div>,
    document.body,
  )
}
