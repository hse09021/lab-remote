import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './Pill.module.css'

export type PillTone = 'neutral' | 'success' | 'warn' | 'solid'

interface Props {
  tone?: PillTone
  /** meta = 헤더 칩(3px 10px), status = 표 상태 칩(4px 10px, 굵게) */
  variant?: 'meta' | 'status'
  children: ReactNode
  className?: string
}

export function Pill({ tone = 'neutral', variant = 'meta', children, className }: Props) {
  return <span className={clsx(s.pill, s[variant], s[tone], className)}>{children}</span>
}
