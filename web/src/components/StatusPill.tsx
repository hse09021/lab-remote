import { useRef, useState } from 'react'
import clsx from 'clsx'
import type { ReadStatus } from '@/api/types'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './StatusPill.module.css'

export const READ_STATUS_LABEL: Record<ReadStatus, string> = {
  todo: '읽을 예정',
  reading: '읽는 중',
  done: '완료',
}

const ORDER: ReadStatus[] = ['todo', 'reading', 'done']

interface Props {
  status: ReadStatus
  /** 주면 드롭다운으로 바꿀 수 있어요. 없으면 표시만 해요 */
  onChange?: (status: ReadStatus) => void
  size?: 'sm' | 'md' | 'lg'
  /** 드롭다운 버튼의 스크린 리더 이름. "Attention Is All You Need 읽음 상태" */
  label?: string
  className?: string
}

/**
 * 읽음 상태 알약. 목업에서는 라이브러리(30px) · 리더(28px) · 모바일(11.5px)로
 * 크기만 달랐고 색과 드롭다운 마크업은 같았어요.
 */
export function StatusPill({ status, onChange, size = 'md', label, className }: Props) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useOutsideClick(wrap, () => setOpen(false), open)

  const pill = (
    <span className={clsx(s.pill, s[size], s[status], className)}>
      {READ_STATUS_LABEL[status]}
    </span>
  )

  if (!onChange) return pill

  return (
    <div ref={wrap} className={s.wrap}>
      <button
        type="button"
        data-interactive="true"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label ?? '읽음 상태 바꾸기'}
        onClick={() => setOpen((v) => !v)}
        className={clsx(s.pill, s[size], s[status], className)}
      >
        {READ_STATUS_LABEL[status]}
        <span aria-hidden="true" className={s.caret}>
          ▾
        </span>
      </button>

      {open && (
        <div role="menu" className={s.menu}>
          {ORDER.map((key) => (
            <button
              key={key}
              type="button"
              role="menuitemradio"
              aria-checked={key === status}
              onClick={() => {
                onChange(key)
                setOpen(false)
              }}
              className={s.item}
            >
              <span aria-hidden="true" className={s.mark}>
                {key === status ? '✓' : ''}
              </span>
              {READ_STATUS_LABEL[key]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
