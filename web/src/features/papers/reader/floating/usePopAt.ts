import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

/**
 * 목업의 popAt과 같은 자리 계산.
 * 떠 있는 카드가 오른쪽으로 넘쳐 가로 스크롤을 만들지 않도록
 * left 를 담은 요소의 **보이는 폭** 안으로 묶어요.
 *
 * 목업은 `a.w`(본문 폭)를 넘겨 받았지만, 여기서는 카드가 실제로 얹힌
 * 스크롤 컨테이너를 재서 확대·패널 너비가 바뀌어도 맞게 해요.
 */
export function usePopAt(x: number, y: number, width: number, gap = 8) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [avail, setAvail] = useState<number | null>(null)

  const measure = useCallback(() => {
    const parent = ref.current?.offsetParent as HTMLElement | null
    if (parent) setAvail(parent.clientWidth)
  }, [])

  useLayoutEffect(() => {
    measure()
    const parent = ref.current?.offsetParent as HTMLElement | null
    if (!parent) return
    const ro = new ResizeObserver(measure)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [measure])

  const maxX = avail === null ? x : Math.max(12, avail - width - 16)
  const left = Math.max(12, Math.min(x - 20, maxX))
  const style: CSSProperties = {
    left,
    top: y + gap,
    width,
    maxWidth: 'calc(100% - 24px)',
    boxSizing: 'border-box',
  }

  return { ref, style, left, avail }
}
