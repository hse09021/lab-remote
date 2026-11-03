import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './SectionHeader.module.css'

interface Props {
  title: string
  /** 오른쪽 보조 영역. 문자열이면 12px 회색으로 깔끔하게 나와요 */
  aside?: ReactNode
  /** 파일 경로 같은 건 mono로 */
  asideMono?: boolean
  align?: 'baseline' | 'center'
  className?: string
}

export function SectionHeader({
  title,
  aside,
  asideMono = false,
  align = 'baseline',
  className,
}: Props) {
  return (
    <div className={clsx(s.header, s[align], className)}>
      <h2 className={s.title}>{title}</h2>
      {typeof aside === 'string' ? (
        <span className={clsx(s.aside, asideMono && s.mono)}>{aside}</span>
      ) : (
        aside
      )}
    </div>
  )
}
