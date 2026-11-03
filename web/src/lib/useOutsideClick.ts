import { useEffect } from 'react'
import type { RefObject } from 'react'

/**
 * 바깥 클릭과 Esc로 닫기.
 * 목업의 드롭다운·팝오버에는 둘 다 없었어요 — 공통으로 한 번만 넣어요.
 */
export function useOutsideClick(
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
  active = true,
) {
  useEffect(() => {
    if (!active) return

    const onPointerDown = (e: globalThis.PointerEvent) => {
      const el = ref.current
      if (el && e.target instanceof Node && !el.contains(e.target)) onClose()
    }
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [ref, onClose, active])
}
