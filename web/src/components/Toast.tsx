import { createPortal } from 'react-dom'
import clsx from 'clsx'
import s from './Toast.module.css'

interface Props {
  message: string
  /** 데스크톱은 위쪽 가운데, 모바일은 아래쪽 */
  placement?: 'top' | 'bottom'
}

/**
 * 토스트 표시. 사라지는 시점은 useToast가 관리해요.
 */
export function Toast({ message, placement = 'top' }: Props) {
  if (!message) return null
  return createPortal(
    <div role="status" aria-live="polite" className={clsx(s.toast, s[placement])}>
      {message}
    </div>,
    document.body,
  )
}
