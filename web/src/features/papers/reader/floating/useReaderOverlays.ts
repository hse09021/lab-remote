import { useCallback, useState } from 'react'
import type { ChatAnchor } from './useFloatingChat'
import type { SelectionAnchor } from './SelectionMenu'
import type { CiteAnchor } from './CiteCard'
import type { SelectionPlace } from '../selectionPlace'

/**
 * 본문 위에 뜨는 것들을 한 곳에서 관리해요.
 * 하나가 열리면 나머지는 닫혀요 (목업과 같은 동작).
 */
export function useReaderOverlays() {
  const [selection, setSelection] = useState<{
    anchor: SelectionAnchor
    text: string
    sectionId: string
    /** 본문에 다시 그릴 자리 (HTML 오프셋 / PDF pt) */
    place: SelectionPlace
  } | null>(null)
  const [cite, setCite] = useState<{ n: number; anchor: CiteAnchor } | null>(null)
  const [popover, setPopover] = useState<{
    kind: 'translate' | 'note'
    anchor: SelectionAnchor
    /** 팝오버를 열면 선택은 닫히니 선택한 텍스트 · 섹션·자리를 들고 가요 */
    text: string
    sectionId: string
    place: SelectionPlace | null
  } | null>(null)
  const closeAll = useCallback(() => {
    setSelection(null)
    setCite(null)
    setPopover(null)
  }, [])

  const openSelection = useCallback(
    (anchor: SelectionAnchor, text: string, sectionId: string, place: SelectionPlace) => {
      setCite(null)
      setPopover(null)
      setSelection({ anchor, text, sectionId, place })
    },
    [],
  )

  const openCite = useCallback((n: number, anchor: CiteAnchor) => {
    setSelection(null)
    setPopover(null)
    setCite({ n, anchor })
  }, [])

  const openPopover = useCallback(
    (
      kind: 'translate' | 'note',
      anchor: SelectionAnchor,
      text: string,
      sectionId: string,
      place: SelectionPlace | null = null,
    ) => {
      setSelection(null)
      setPopover({ kind, anchor, text, sectionId, place })
    },
    [],
  )

  return {
    selection,
    cite,
    popover,
    closeAll,
    openSelection,
    openCite,
    openPopover,
    setPopover,
  }
}

/** 화면 좌표를 스크롤 컨테이너 기준 좌표로 */
export function anchorFrom(el: HTMLElement, root: HTMLElement): ChatAnchor & SelectionAnchor {
  const r = el.getBoundingClientRect()
  const rr = root.getBoundingClientRect()
  return {
    x: r.left - rr.left + root.scrollLeft,
    y: r.bottom - rr.top + root.scrollTop,
    width: r.width,
  }
}

export function anchorFromRect(
  rect: DOMRect,
  root: HTMLElement,
): ChatAnchor & SelectionAnchor {
  const rr = root.getBoundingClientRect()
  return {
    x: rect.left - rr.left + root.scrollLeft,
    y: rect.bottom - rr.top + root.scrollTop,
    width: rect.width,
  }
}
