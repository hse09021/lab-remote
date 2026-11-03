import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './SplitButton.module.css'

export interface SplitMenuItem {
  label: string
  /** 내부 라우트로 이동할 때 */
  to?: string
  onSelect?: () => void
}

interface Props {
  label: string
  onClick?: () => void
  /** 캐럿 버튼의 스크린 리더 이름 */
  menuLabel: string
  items: SplitMenuItem[]
  menuWidth?: number
  /** 메뉴 아래에 붙는 입력 영역 (논문 업로드의 URL 칸) */
  footer?: ReactNode
}

/**
 * 주 버튼 + 캐럿 메뉴. 목업의 "새 실험"이 이 모양이에요.
 * 목업에는 없던 바깥 클릭·Esc 닫기를 넣었어요.
 */
export function SplitButton({
  label,
  onClick,
  menuLabel,
  items,
  menuWidth = 300,
  footer,
}: Props) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useOutsideClick(wrap, () => setOpen(false), open)

  return (
    <div ref={wrap} className={s.wrap}>
      <button type="button" onClick={onClick} className={s.main}>
        {label}
      </button>
      <button
        type="button"
        aria-label={`${menuLabel} 더보기`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={s.caret}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          aria-label={menuLabel}
          style={{ width: menuWidth }}
          className={s.menu}
        >
          {items.map((item) =>
            item.to ? (
              <Link
                key={item.label}
                to={item.to}
                role="menuitem"
                onClick={() => setOpen(false)}
                className={s.item}
              >
                {item.label}
              </Link>
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                onClick={() => {
                  item.onSelect?.()
                  setOpen(false)
                }}
                className={s.item}
              >
                {item.label}
              </button>
            ),
          )}
          {footer && <div className={s.footer}>{footer}</div>}
        </div>
      )}
    </div>
  )
}
