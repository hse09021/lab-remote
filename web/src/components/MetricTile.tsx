import type { ReactNode } from 'react'
import type { MetricTileData } from '@/api/types'
import { ProgressBar } from './ProgressBar'
import s from './MetricTile.module.css'

export function MetricTileRow({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <section aria-label={label} className={s.row}>
      {children}
    </section>
  )
}

export function MetricTile({ tile }: { tile: MetricTileData }) {
  return (
    <div className={s.tile}>
      <span className={s.label}>{tile.label}</span>
      <span data-tone={tile.valueTone} className={s.value}>
        {tile.value}
        {tile.valueSuffix && <span className={s.suffix}>{tile.valueSuffix}</span>}
      </span>
      {tile.progress !== null && (
        <ProgressBar value={tile.progress} label={`${tile.label} 진행률`} />
      )}
      <span data-tone={tile.subTone} className={s.sub}>
        {tile.sub}
      </span>
    </div>
  )
}
