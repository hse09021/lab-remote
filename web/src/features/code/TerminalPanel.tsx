import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react'
import type { TerminalLine, TerminalPayload } from '@/api/types'
import { Resizer } from '@/components'
import { useOutsideClick } from '@/lib/useOutsideClick'
import { usePaneResize } from '@/lib/usePaneResize'
import s from './TerminalPanel.module.css'

/**
 * 목업에는 터미널 하나뿐이었어요.
 * VS Code 처럼 여러 개를 열고, 분할하고, 목록에서 고를 수 있게 했어요.
 */
export interface TerminalTab {
  id: string
  /** 목록에 굵게 나오는 이름 (bash · npm …) */
  name: string
  /** 그 옆에 흐리게 나오는 설명 (작업 폴더) */
  detail: string
  kind: TerminalKind
  /** 분할하면 같은 묶음이 돼요 */
  groupId: string
}

export type TerminalKind = 'bash' | 'tmux' | 'npm'

export const TERMINAL_PROFILES: Array<{ id: TerminalKind; label: string }> = [
  { id: 'bash', label: 'bash' },
  { id: 'tmux', label: 'tmux' },
  { id: 'npm', label: 'npm' },
]

const CWD = 'lab-remote'

/** 분할 칸이 이보다 좁아지지 않아요 */
const MIN_PANE_PX = 160

/**
 * 터미널 상태. 패널과 툴바가 같이 써야 해서 훅으로 뺐어요.
 */
export function useTerminals(data: TerminalPayload | undefined) {
  const session = data?.session?.split('·').pop()?.trim() || 'exp-007'

  const [tabs, setTabs] = useState<TerminalTab[]>(() => [
    { id: 't1', name: 'tmux', detail: session, kind: 'tmux', groupId: 'g1' },
  ])
  const [activeId, setActiveId] = useState('t1')
  const seq = useRef(1)

  const active = tabs.find((t) => t.id === activeId) ?? tabs[0]

  const add = useCallback((kind: TerminalKind, groupId?: string) => {
    seq.current += 1
    const tab: TerminalTab = {
      id: `t${seq.current}`,
      name: kind,
      detail: CWD,
      kind,
      groupId: groupId ?? `g${seq.current}`,
    }
    setTabs((prev) => [...prev, tab])
    setActiveId(tab.id)
  }, [])

  const split = useCallback(() => {
    // 업데이터 안에서 다른 상태를 바꾸면 StrictMode 에서 두 번 돌아요 — 밖에서 계산해요
    const cur = tabs.find((t) => t.id === activeId) ?? tabs[0]
    if (!cur) return
    seq.current += 1
    const tab: TerminalTab = {
      id: `t${seq.current}`,
      name: cur.kind,
      detail: CWD,
      kind: cur.kind,
      groupId: cur.groupId,
    }
    // 분할한 것은 원본 바로 뒤에 넣어요 (목록에서 묶여 보이게)
    setTabs((prev) => {
      const at = prev.findIndex((t) => t.id === cur.id)
      return [...prev.slice(0, at + 1), tab, ...prev.slice(at + 1)]
    })
    setActiveId(tab.id)
  }, [tabs, activeId])

  const kill = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.id !== id)
        if (id === activeId) setActiveId(next[0]?.id ?? '')
        return next
      })
    },
    [activeId],
  )

  return { tabs, activeId, active, setActiveId, add, split, kill }
}

export type Terminals = ReturnType<typeof useTerminals>

/* ── 패널 본문 ────────────────────────────────────────────── */

export function TerminalPanel({
  data,
  terminals,
}: {
  data: TerminalPayload | undefined
  terminals: Terminals
}) {
  const { tabs, activeId, active, setActiveId, split, kill } = terminals
  const shown = active ? tabs.filter((t) => t.groupId === active.groupId) : []
  // VS Code 처럼 목록 너비를 끌어서 바꿔요
  const list = usePaneResize({ initial: 196, min: 120, max: 420, dir: -1 })

  /* 분할한 칸은 비율(flex)로 나눠 가져요 */
  const panesRef = useRef<HTMLDivElement>(null)
  const [flex, setFlex] = useState<Record<string, number>>({})
  const drag = useRef<{
    left: string
    right: string
    x: number
    l: number
    r: number
    /* 보이는 칸들의 flex 합 — px 이동을 flex 로 바꿀 때 써요 */
    sum: number
  } | null>(null)

  /** 두 칸 사이에서 비율을 옮겨요. 양쪽 다 MIN_PANE_PX 보다 좁아지지 않아요 */
  const shift = useCallback((left: string, right: string, deltaPx: number) => {
    const box = panesRef.current
    if (!box || !box.clientWidth) return

    setFlex((prev) => {
      const l = prev[left] ?? 1
      const r = prev[right] ?? 1
      const total = l + r
      // 이 줄의 flex 합으로 px ↔ flex 를 환산해요
      const sum = [...box.children]
        .filter((el) => el instanceof HTMLElement && el.tagName === 'SECTION')
        .reduce((n, el) => n + Number(getComputedStyle(el).flexGrow || 1), 0)
      const perFlex = box.clientWidth / (sum || total)
      const minFlex = Math.min(total / 2, MIN_PANE_PX / perFlex)

      const nextL = Math.min(total - minFlex, Math.max(minFlex, l + deltaPx / perFlex))
      return { ...prev, [left]: nextL, [right]: total - nextL }
    })
  }, [])

  useEffect(() => {
    const onMove = (e: globalThis.PointerEvent) => {
      const d = drag.current
      const box = panesRef.current
      if (!d || !box) return
      const width = box.clientWidth
      if (!width) return

      // flex 1 당 몇 px 인지로 환산해요
      const perFlex = width / d.sum
      const total = d.l + d.r
      const minFlex = Math.min(total / 2, MIN_PANE_PX / perFlex)
      const nextL = Math.min(
        total - minFlex,
        Math.max(minFlex, d.l + (e.clientX - d.x) / perFlex),
      )
      setFlex((prev) => ({ ...prev, [d.left]: nextL, [d.right]: total - nextL }))
    }
    const onUp = () => {
      drag.current = null
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  const startPaneDrag = (e: ReactPointerEvent<HTMLElement>, left: string, right: string) => {
    e.preventDefault()
    drag.current = {
      left,
      right,
      x: e.clientX,
      l: flex[left] ?? 1,
      r: flex[right] ?? 1,
      sum: shown.reduce((n, t) => n + (flex[t.id] ?? 1), 0),
    }
  }

  const nudgePane = (e: ReactKeyboardEvent<HTMLElement>, left: string, right: string) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    shift(left, right, e.key === 'ArrowRight' ? 24 : -24)
  }

  /** 같은 묶음이 둘 이상이면 분할된 거예요 — 목록에 연결선을 그려요 */
  const groupSize = (groupId: string) => tabs.filter((t) => t.groupId === groupId).length
  const indexInGroup = (t: TerminalTab) =>
    tabs.filter((x) => x.groupId === t.groupId).findIndex((x) => x.id === t.id)

  return (
    <div className={s.wrap}>
      {shown.length === 0 ? (
        <p className={s.empty}>열린 터미널이 없어요 · + 로 새로 열 수 있어요</p>
      ) : (
        <div ref={panesRef} className={s.panes} data-split={shown.length > 1 ? 'true' : undefined}>
          {shown.map((t, i) => (
            <Fragment key={t.id}>
              {i > 0 && (
                <button
                  type="button"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`${shown[i - 1].name} · ${t.name} 칸 너비 조절`}
                  onPointerDown={(e) => startPaneDrag(e, shown[i - 1].id, t.id)}
                  onKeyDown={(e) => nudgePane(e, shown[i - 1].id, t.id)}
                  className={s.paneSplit}
                />
              )}
              <section
                aria-label={`터미널 ${t.name} ${t.detail}`}
                data-active={t.id === activeId ? 'true' : undefined}
                style={{ flex: `${flex[t.id] ?? 1} 1 0`, minWidth: 0 }}
                onClick={() => setActiveId(t.id)}
                className={s.pane}
              >
                <Lines lines={data?.lines ?? []} fresh={t.id !== 't1'} />
              </section>
            </Fragment>
          ))}
        </div>
      )}

      {/* 목록은 터미널이 둘 이상일 때만 보여요 (VS Code 와 같게) */}
      {tabs.length > 1 && (
        <>
          <Resizer handle={list.resizerProps} label="터미널 목록 너비 조절" />

          <ul style={list.style} className={s.list} aria-label="터미널 목록">
            {tabs.map((t) => {
              const size = groupSize(t.groupId)
              const i = indexInGroup(t)
              const connector = size < 2 ? null : i === 0 ? 'top' : i === size - 1 ? 'bottom' : 'mid'
              return (
                <li key={t.id}>
                  <div
                    className={s.row}
                    data-active={t.id === activeId ? 'true' : undefined}
                    data-split={connector ?? undefined}
                  >
                    <button
                      type="button"
                      aria-current={t.id === activeId ? 'true' : undefined}
                      onClick={() => setActiveId(t.id)}
                      className={s.rowMain}
                    >
                      {connector && (
                        <span aria-hidden="true" className={s.connector}>
                          {connector === 'bottom' ? '└' : '┌'}
                        </span>
                      )}
                      <TerminalIcon />
                      <span className={s.rowName}>{t.name}</span>
                      <span className={s.rowDetail}>{t.detail}</span>
                    </button>
                    <div className={s.rowActions}>
                      <button
                        type="button"
                        aria-label={`${t.name} 터미널 분할`}
                        title="터미널 분할"
                        onClick={() => {
                          setActiveId(t.id)
                          split()
                        }}
                        className={s.rowAction}
                      >
                        <SplitIcon />
                      </button>
                      <button
                        type="button"
                        aria-label={`${t.name} 터미널 종료`}
                        title="터미널 종료"
                        onClick={() => kill(t.id)}
                        className={s.rowAction}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </div>
                </li>
                )
              })}
          </ul>
        </>
      )}
    </div>
  )
}

function Lines({ lines, fresh }: { lines: TerminalLine[]; fresh: boolean }) {
  // 새로 연 터미널은 프롬프트 한 줄만 보여요
  const rows = fresh ? lines.filter((l) => l.kind === 'prompt') : lines

  return (
    <div className={s.lines}>
      {rows.map((l, i) => (
        <div key={i}>
          {l.kind === 'prompt' ? (
            <>
              <span className={s.user}>{l.user}</span>:<span className={s.path}>{l.path}</span>
              {l.text}
              <span aria-hidden="true">_</span>
            </>
          ) : (
            l.text
          )}
        </div>
      ))}
    </div>
  )
}

/* ── 패널 툴바 (탭 줄 오른쪽) ─────────────────────────────── */

export function TerminalToolbar({
  terminals,
  maximized,
  onToggleMaximize,
  onClose,
}: {
  terminals: Terminals
  maximized: boolean
  onToggleMaximize: () => void
  onClose: () => void
}) {
  const { tabs, active, add, split, kill } = terminals
  // 하나뿐일 때는 이름·분할·종료를 툴바에 둬요. 둘 이상이면 목록이 그 일을 해요
  const single = tabs.length === 1
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useOutsideClick(menuRef, () => setOpen(false), open)

  /* VS Code 와 같은 단축키 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || !e.shiftKey) return
      if (e.key === '`') {
        e.preventDefault()
        add('bash')
      }
      if (e.key === '5' || e.code === 'Digit5') {
        e.preventDefault()
        split()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [add, split])

  return (
    <div className={s.toolbar}>
      <div ref={menuRef} className={s.newWrap}>
        <button
          type="button"
          aria-label="새 터미널"
          title="새 터미널 (Ctrl+Shift+`)"
          onClick={() => add('bash')}
          className={s.toolBtn}
        >
          <PlusIcon />
        </button>
        <button
          type="button"
          aria-label="터미널 메뉴"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className={s.caret}
        >
          <CaretIcon />
        </button>

        {open && (
          <div role="menu" aria-label="터미널 메뉴" className={s.menu}>
            <MenuItem
              label="새 터미널"
              hint="Ctrl+Shift+`"
              onPick={() => {
                add('bash')
                setOpen(false)
              }}
            />
            <MenuItem
              label="터미널 분할"
              hint="Ctrl+Shift+5"
              onPick={() => {
                split()
                setOpen(false)
              }}
            />
            <div role="separator" className={s.menuSep} />
            {TERMINAL_PROFILES.map((p) => (
              <MenuItem
                key={p.id}
                label={p.label}
                mono
                onPick={() => {
                  add(p.id)
                  setOpen(false)
                }}
              />
            ))}
            <div role="separator" className={s.menuSep} />
            <MenuItem label="기본 프로필 선택" disabled />
            <MenuItem label="터미널 설정 구성" disabled />
          </div>
        )}
      </div>

      {single && active && (
        <>
          <span className={s.current}>
            <TerminalIcon />
            {active.name} - {active.detail}
          </span>
          <button
            type="button"
            aria-label="터미널 분할"
            title="터미널 분할 (Ctrl+Shift+5)"
            onClick={split}
            className={s.toolBtn}
          >
            <SplitIcon />
          </button>
          <button
            type="button"
            aria-label="터미널 종료"
            title="터미널 종료"
            onClick={() => kill(active.id)}
            className={s.toolBtn}
          >
            <TrashIcon />
          </button>
          <span aria-hidden="true" className={s.toolSep} />
        </>
      )}

      <button
        type="button"
        aria-label={maximized ? '패널 복원' : '패널 최대화'}
        title={maximized ? '패널 복원' : '패널 최대화'}
        aria-pressed={maximized}
        onClick={onToggleMaximize}
        className={s.toolBtn}
      >
        <MaximizeIcon />
      </button>

      <button
        type="button"
        aria-label="패널 닫기"
        title="패널 닫기"
        onClick={onClose}
        className={s.toolBtn}
      >
        <CloseIcon />
      </button>
    </div>
  )
}

function MenuItem({
  label,
  hint,
  mono,
  disabled,
  onPick,
}: {
  label: string
  hint?: string
  mono?: boolean
  disabled?: boolean
  onPick?: () => void
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onPick}
      className={s.menuItem}
    >
      <span className={mono ? s.menuMono : undefined}>{label}</span>
      {hint && <span className={s.menuHint}>{hint}</span>}
    </button>
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

function TerminalIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 3-3 3M13 15h4" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function CaretIcon() {
  // 24 뷰박스에 10px 로 그리면 선이 0.75px 이 돼 거의 안 보여요
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 4.5L6 7.5 9 4.5" />
    </svg>
  )
}

function SplitIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M12 4v16" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
    </svg>
  )
}

function MaximizeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M4 9V4h5M20 15v5h-5M20 9V4h-5M4 15v5h5" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
}
