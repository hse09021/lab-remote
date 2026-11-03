import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './DividedRow.module.css'

export function DividedRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div aria-label={label} className={s.row}>
      {children}
    </div>
  )
}

export function DividedCell({
  gap = 10,
  children,
  className,
}: {
  gap?: number
  children: ReactNode
  className?: string
}) {
  return (
    <div style={{ gap }} className={clsx(s.cell, className)}>
      {children}
    </div>
  )
}
