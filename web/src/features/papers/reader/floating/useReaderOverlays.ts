import { useCallback, useRef, useState } from 'react'
import type { ChatAnchor } from './useFloatingChat'
import type { SelectionAnchor } from './SelectionMenu'
import type { CiteAnchor } from './CiteCard'

export interface UserNote {
  id: string
  kind: 'highlight' | 'note'
  /** 하이라이트는 고른 글, 주석은 내가 쓴 메모 */
  text: string
  /** 주석일 때 어떤 글에 달았는지 */
  source?: string
  /** 보여 줄 위치 라벨 (예: §3.2.1) */
  where: string
  sectionId: string
}

/**
 * 본문 위에 뜨는 것들을 한 곳에서 관리해요.
 * 하나가 열리면 나머지는 닫혀요 (목업과 같은 동작).
 */
export function useReaderOverlays() {
  const [selection, setSelection] = useState<{
    anchor: SelectionAnchor
    text: string
    sectionId: string
  } | null>(null)
  const [cite, setCite] = useState<{ n: number; anchor: CiteAnchor } | null>(null)
  const [popover, setPopover] = useState<{
    kind: 'translate' | 'note'
    anchor: SelectionAnchor
    /** 팝오버를 열면 선택은 닫히니 고른 글과 섹션을 들고 가요 */
    text: string
    sectionId: string
  } | null>(null)
  /** 사용자가 직접 친 하이라이트·주석 */
  const [userNotes, setUserNotes] = useState<UserNote[]>([])
  /**
   * 토글 결과(켰는지 껐는지)를 부른 쪽이 바로 알아야 토스트 문구를 고를 수 있어요.
   * setState 업데이터는 즉시 실행이 보장되지 않으니 최신 값을 ref로 따로 들고 있어요.
   */
  const notesRef = useRef<UserNote[]>([])
  const seq = useRef(0)

  const closeAll = useCallback(() => {
    setSelection(null)
    setCite(null)
    setPopover(null)
  }, [])

  const openSelection = useCallback(
    (anchor: SelectionAnchor, text: string, sectionId: string) => {
      setCite(null)
      setPopover(null)
      setSelection({ anchor, text, sectionId })
    },
    [],
  )

  const openCite = useCallback((n: number, anchor: CiteAnchor) => {
    setSelection(null)
    setPopover(null)
    setCite({ n, anchor })
  }, [])

  const openPopover = useCallback(
    (kind: 'translate' | 'note', anchor: SelectionAnchor, text: string, sectionId: string) => {
      setSelection(null)
      setPopover({ kind, anchor, text, sectionId })
    },
    [],
  )

  const toggleUserHighlight = useCallback(
    (text: string, where: string, sectionId: string) => {
      const i = notesRef.current.findIndex((n) => n.kind === 'highlight' && n.text === text)
      const next: UserNote[] =
        i >= 0
          ? notesRef.current.filter((_, j) => j !== i)
          : [
              { id: `u-${++seq.current}`, kind: 'highlight', text, where, sectionId },
              ...notesRef.current,
            ]
      notesRef.current = next
      setUserNotes(next)
      return i < 0
    },
    [],
  )

  const addUserNote = useCallback(
    (text: string, source: string, where: string, sectionId: string) => {
      const next: UserNote[] = [
        { id: `n-${++seq.current}`, kind: 'note', text, source, where, sectionId },
        ...notesRef.current,
      ]
      notesRef.current = next
      setUserNotes(next)
    },
    [],
  )

  return {
    selection,
    cite,
    popover,
    userNotes,
    closeAll,
    openSelection,
    openCite,
    openPopover,
    setPopover,
    toggleUserHighlight,
    addUserNote,
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
