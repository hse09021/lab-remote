import type { UserAnnotation } from '@/api/annotations'
import type { SelectionAnchor } from './SelectionMenu'
import { usePopAt } from './usePopAt'
import s from './MyHighlightMenu.module.css'

interface Props {
  annotation: UserAnnotation
  anchor: SelectionAnchor
  onAnnotate: () => void
  onDelete: () => void
  onClose: () => void
}

/**
 * 본문에서 내 하이라이트를 누르면 뜨는 작은 메뉴.
 * AI 하이라이트는 논문 데이터라 이 메뉴가 뜨지 않아요 (메모 카드가 떠요).
 */
export function MyHighlightMenu({ annotation, anchor, onAnnotate, onDelete, onClose }: Props) {
  const { ref, style } = usePopAt(anchor.x, anchor.y, 200)

  return (
    <div
      ref={ref}
      role="menu"
      aria-label="내 하이라이트"
      style={style}
      data-reader-overlay=""
      className={s.menu}
    >
      <span className={s.quote}>{annotation.text}</span>
      <button type="button" role="menuitem" onClick={onAnnotate} className={s.item}>
        주석 달기
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onDelete}
        className={`${s.item} ${s.danger}`}
      >
        삭제
      </button>
      <button type="button" role="menuitem" onClick={onClose} className={s.item}>
        닫기
      </button>
    </div>
  )
}
