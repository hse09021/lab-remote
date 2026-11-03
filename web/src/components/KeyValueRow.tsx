import type { KeyValue } from '@/api/types'
import s from './KeyValueRow.module.css'

export function KeyValueRow({ item }: { item: KeyValue }) {
  return (
    <div className={s.row}>
      <span>{item.label}</span>
      <span data-tone={item.tone} className={s.value}>
        {item.value}
      </span>
    </div>
  )
}
