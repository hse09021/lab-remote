import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './Banner.module.css'

interface Props {
  tone?: 'warn' | 'neutral'
  /** 접근성 이름. "승인 대기" */
  label: string
  /** 왼쪽 굵은 라벨. "승인 대기 1" */
  badge?: ReactNode
  icon?: ReactNode
  children: ReactNode
  action?: ReactNode
}

export function Banner({ tone = 'warn', label, badge, icon, children, action }: Props) {
  return (
    <section aria-label={label} className={clsx(s.banner, s[tone])}>
      {icon}
      {badge && <span className={s.label}>{badge}</span>}
      <span className={s.body}>{children}</span>
      {action}
    </section>
  )
}
