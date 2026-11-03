import { useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { useFocusTrap, useScrollLock } from '@/lib/useFocusTrap'
import s from './Sheet.module.css'

interface Props {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

/**
 * 모바일 바텀시트. 목업(FocusMobile)의 권한 프리셋 · 정지 확인 · 논문 요약
 * 세 가지가 같은 껍데기를 써요.
 * 목업에 없던 포커스 트랩 · Esc · 배경 스크롤 잠금을 넣었어요.
 */
export function Sheet({ open, title, onClose, children }: Props) {
  const sheet = useRef<HTMLDivElement>(null)
  useFocusTrap(sheet, open)
  useScrollLock(open)

  if (!open) return null

  return createPortal(
    <div
      className={s.overlay}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <button type="button" aria-label="닫기" onClick={onClose} className={s.scrim} />

      <section
        ref={sheet}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={s.sheet}
      >
        <span aria-hidden="true" className={s.grabber} />
        <div className={s.titleRow}>
          <h2 className={s.title}>{title}</h2>
          <button type="button" aria-label="닫기" onClick={onClose} className={s.close}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        {children}
      </section>
    </div>,
    document.body,
  )
}
