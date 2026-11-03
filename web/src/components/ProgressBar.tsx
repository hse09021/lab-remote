import clsx from 'clsx'
import s from './ProgressBar.module.css'

interface Props {
  /** 0–100 */
  value: number
  tone?: 'accent' | 'attention' | 'neutral'
  height?: number
  /** 채움도 둥글게. 자원 막대가 이 모양이에요 */
  rounded?: boolean
  label?: string
}

export function ProgressBar({
  value,
  tone = 'accent',
  height = 6,
  rounded = false,
  label,
}: Props) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div
      role={label ? 'progressbar' : undefined}
      aria-label={label}
      aria-valuenow={label ? pct : undefined}
      aria-valuemin={label ? 0 : undefined}
      aria-valuemax={label ? 100 : undefined}
      style={{ height }}
      className={clsx(s.track, rounded ? s.round : s.clip)}
    >
      <div style={{ width: `${pct}%` }} className={clsx(s.fill, s[tone])} />
    </div>
  )
}
