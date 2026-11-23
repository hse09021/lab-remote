import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { UserAnnotation } from '@/api/annotations'
import { rangeFromAnchor } from './selectionPlace'
import s from './MyHighlightLayer.module.css'

interface Mark {
  annotation: UserAnnotation
  /** 스크롤 컨테이너 기준 좌표 */
  left: number
  top: number
  width: number
  height: number
}

interface Props {
  /** 주입된 본문 */
  bodyRef: RefObject<HTMLDivElement | null>
  /** 좌표 기준이 되는 스크롤 컨테이너 */
  scrollRef: RefObject<HTMLDivElement | null>
  annotations: UserAnnotation[]
  /** 본문이 다시 그려졌는지 알려 주는 값 (html, 창 크기 등) */
  revision: unknown
  onPick: (annotation: UserAnnotation, rect: DOMRect) => void
}

/**
 * HTML 보기에 내가 칠한 하이라이트를 다시 그려요.
 * 주입된 HTML을 건드리지 않고, 블록 id + 글자 오프셋으로 Range를 되살려
 * 그 줄 사각형만큼 덮어요 (줄바꿈이 있으면 여러 조각이 돼요).
 */
export function MyHighlightLayer({
  bodyRef,
  scrollRef,
  annotations,
  revision,
  onPick,
}: Props) {
  const [marks, setMarks] = useState<Mark[]>([])
  const raf = useRef<number | null>(null)

  const measure = useCallback(() => {
    const body = bodyRef.current
    const scroller = scrollRef.current
    if (!body || !scroller) return

    const base = scroller.getBoundingClientRect()
    const next: Mark[] = []

    for (const a of annotations) {
      if (!a.anchor) continue
      const range = rangeFromAnchor(body, a.anchor)
      if (!range) continue
      for (const r of Array.from(range.getClientRects())) {
        if (r.width < 1 || r.height < 1) continue
        next.push({
          annotation: a,
          left: r.left - base.left + scroller.scrollLeft,
          top: r.top - base.top + scroller.scrollTop,
          width: r.width,
          height: r.height,
        })
      }
    }
    setMarks(next)
  }, [annotations, bodyRef, scrollRef])

  useEffect(() => {
    // 본문·글꼴이 자리를 잡은 다음에 재요
    const schedule = () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
      raf.current = requestAnimationFrame(() => {
        raf.current = null
        measure()
      })
    }
    schedule()

    const body = bodyRef.current
    const ro = body ? new ResizeObserver(schedule) : null
    if (body && ro) ro.observe(body)
    window.addEventListener('resize', schedule)

    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
      ro?.disconnect()
      window.removeEventListener('resize', schedule)
    }
  }, [measure, revision, bodyRef])

  return (
    <>
      {marks.map((m, i) => (
        <button
          key={`${m.annotation.id}-${i}`}
          type="button"
          aria-label={`내 하이라이트 · ${m.annotation.text.slice(0, 24)}`}
          style={{ left: m.left, top: m.top, width: m.width, height: m.height }}
          onClick={(e) => onPick(m.annotation, e.currentTarget.getBoundingClientRect())}
          className={s.mark}
        />
      ))}
    </>
  )
}
