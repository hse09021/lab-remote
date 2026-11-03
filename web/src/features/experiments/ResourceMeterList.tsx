import type { ResourceMeter } from '@/api/types'
import { ProgressBar } from '@/components'
import s from './ResourceMeterList.module.css'

export function ResourceMeterList({ rows }: { rows: ResourceMeter[] }) {
  return (
    <div className={s.grid}>
      {rows.map((r) => (
        <Row key={r.label} meter={r} />
      ))}
    </div>
  )
}

function Row({ meter }: { meter: ResourceMeter }) {
  return (
    <>
      <span className={s.label}>{meter.label}</span>
      <div className={s.bar}>
        <ProgressBar value={meter.pct} tone={meter.tone} rounded label={meter.label} />
      </div>
      <span data-tone={meter.tone} className={s.value}>
        {meter.value}
      </span>
    </>
  )
}
