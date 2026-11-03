import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, PointerEvent } from 'react'

/**
 * 패널 크기 조절 + 접기.
 *
 * 목업 6개 파일(FocusLibrary, FocusReader, AltFocus, FocusAuthority,
 * FocusDesign, FocusCode)에 `panes` + `resizeVals` + `startDrag` + `nudge`
 * 네 덩어리가 그대로 복사돼 있었어요. 그걸 이 훅 하나로 모았어요.
 *
 * - `dir: 1`  핸들 왼쪽/위쪽 패널 → 핸들을 끌어 내리면 커져요
 * - `dir: -1` 핸들 오른쪽/아래쪽 패널 → 반대로 움직여요
 * - 키보드는 화살표로 16px씩 (목업과 동일)
 */

const STEP = 16

export interface PaneConfig {
  /** 기본 너비(또는 높이) px */
  initial: number
  min: number
  max: number
  /** 1 = 핸들 앞쪽 패널, -1 = 핸들 뒤쪽 패널 */
  dir: 1 | -1
  /** 'vertical' = 좌우 분할(col-resize), 'horizontal' = 상하 분할(row-resize) */
  orientation?: 'vertical' | 'horizontal'
  /** 접을 수 있으면 true. 접으면 48px 띠로 바뀌어요 */
  collapsible?: boolean
  /** 접기 초기 상태 */
  defaultOpen?: boolean
}

export interface ResizerProps {
  role: 'separator'
  'aria-orientation': 'vertical' | 'horizontal'
  tabIndex: 0
  onPointerDown: (e: PointerEvent<HTMLElement>) => void
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
  'data-orientation': 'vertical' | 'horizontal'
}

export interface PaneResize {
  /** 패널 요소에 그대로 넘기는 style. 접혀 있으면 display:none */
  style: CSSProperties
  /** 현재 크기 px */
  size: number
  setSize: (px: number) => void
  open: boolean
  closed: boolean
  toggle: () => void
  setOpen: (open: boolean) => void
  /** 리사이저 요소에 펼치는 props. 접혀 있으면 null */
  resizerProps: ResizerProps | null
  orientation: 'vertical' | 'horizontal'
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export function usePaneResize(config: PaneConfig): PaneResize {
  const {
    initial,
    min,
    max,
    dir,
    orientation = 'vertical',
    collapsible = false,
    defaultOpen = true,
  } = config

  const [size, setSizeState] = useState(initial)
  const [open, setOpen] = useState(collapsible ? defaultOpen : true)

  // 드래그 중인 값은 state로 두지 않아요 (목업도 this.drag 인스턴스 필드였어요).
  const drag = useRef<{ x: number; y: number; start: number } | null>(null)

  const setSize = useCallback(
    (px: number) => setSizeState(clamp(px, min, max)),
    [min, max],
  )

  useEffect(() => {
    const onMove = (e: globalThis.PointerEvent) => {
      const d = drag.current
      if (!d) return
      const delta = orientation === 'vertical' ? e.clientX - d.x : e.clientY - d.y
      setSizeState(clamp(d.start + dir * delta, min, max))
    }
    const onUp = () => {
      drag.current = null
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [dir, min, max, orientation])

  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      e.preventDefault()
      drag.current = { x: e.clientX, y: e.clientY, start: size }
    },
    [size],
  )

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLElement>) => {
      const grow = orientation === 'vertical' ? 'ArrowRight' : 'ArrowDown'
      const shrink = orientation === 'vertical' ? 'ArrowLeft' : 'ArrowUp'

      if (e.key !== grow && e.key !== shrink) return
      e.preventDefault()
      const step = (e.key === grow ? STEP : -STEP) * dir
      setSizeState((prev) => clamp(prev + step, min, max))
    },
    [dir, min, max, orientation],
  )

  const toggle = useCallback(() => setOpen((v) => !v), [])

  // 목업과 같게 flex-basis로만 크기를 줘요.
  const style: CSSProperties = open
    ? { flex: `0 0 ${size}px`, minWidth: 0, minHeight: 0 }
    : { display: 'none' }

  return {
    style,
    size,
    setSize,
    open,
    closed: !open,
    toggle,
    setOpen,
    resizerProps: open
      ? {
          role: 'separator',
          'aria-orientation': orientation,
          tabIndex: 0,
          onPointerDown,
          onKeyDown,
          'data-orientation': orientation,
        }
      : null,
    orientation,
  }
}
