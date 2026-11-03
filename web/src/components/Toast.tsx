import { createPortal } from 'react-dom'
import clsx from 'clsx'
import s from './Toast.module.css'

export interface ToastAction {
  label: string
  onAct: () => void
}

interface Props {
  message: string
  /** 데스크톱은 위쪽 가운데, 모바일은 아래쪽 */
  placement?: 'top' | 'bottom'
  /** "되돌리기" 처럼 토스트 안에서 바로 누를 수 있는 것 */
  action?: ToastAction | null
}

/**
 * 토스트 표시. 사라지는 시점은 useToast가 관리해요.
 */
export function Toast({ message, placement = 'top', action }: Props) {
  if (!message) return null
  return createPortal(
    <div role="status" aria-live="polite" className={clsx(s.toast, s[placement])}>
      <span>{message}</span>
      {action && (
        <button type="button" onClick={action.onAct} className={s.action}>
          {action.label}
        </button>
      )}
    </div>,
    document.body,
  )
}
