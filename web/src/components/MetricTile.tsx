import clsx from 'clsx'
import type { ReactNode } from 'react'
import type { MetricTileData } from '@/api/types'
import { ProgressBar } from './ProgressBar'
import s from './MetricTile.module.css'

/** lg = 대시보드 요약 지표(26px), md = 종료 조건(22px) */
type Size = 'lg' | 'md'

export function MetricTileRow({
  label,
  size = 'lg',
  children,
}: {
  label: string
  size?: Size
  children: ReactNode
}) {
  return (
    <section aria-label={label} className={clsx(s.row, s[size])}>
      {children}
    </section>
  )
}

export function MetricTile({ tile }: { tile: MetricTileData }) {
  return (
    <div className={s.tile}>
      <span className={s.label}>{tile.label}</span>
      <span
        data-tone={tile.valueTone ?? 'default'}
        data-variant={tile.valueVariant ?? 'numeric'}
        className={s.value}
      >
        {tile.value}
        {tile.valueSuffix && <span className={s.suffix}>{tile.valueSuffix}</span>}
      </span>
      {tile.progress != null && (
        <ProgressBar value={tile.progress} label={`${tile.label} 진행률`} />
      )}
      <span data-tone={tile.subTone ?? 'muted'} className={s.sub}>
        {tile.sub}
      </span>
    </div>
  )
}
