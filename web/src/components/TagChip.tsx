import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './TagChip.module.css'

export function TagChip({
  variant = 'filled',
  children,
}: {
  variant?: 'filled' | 'outline'
  children: ReactNode
}) {
  return <span className={clsx(s.chip, variant === 'outline' && s.outline)}>{children}</span>
}
