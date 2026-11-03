import { useEffect } from 'react'
import type { RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * 모달·시트 안에 포커스를 묶어 두고, 닫힐 때 원래 자리로 돌려줘요.
 * 목업에는 없던 부분이에요.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return
    const el = ref.current
    if (!el) return

    const previous = document.activeElement as HTMLElement | null
    const first = el.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? el).focus()

    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (n) => n.offsetParent !== null,
      )
      if (items.length === 0) return

      const head = items[0]!
      const tail = items[items.length - 1]!

      if (e.shiftKey && document.activeElement === head) {
        e.preventDefault()
        tail.focus()
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault()
        head.focus()
      }
    }

    el.addEventListener('keydown', onKeyDown)
    return () => {
      el.removeEventListener('keydown', onKeyDown)
      previous?.focus()
    }
  }, [ref, active])
}

/** 시트·모달이 열려 있는 동안 배경 스크롤을 막아요 */
export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [active])
}
