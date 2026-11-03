import clsx from 'clsx'
import { Link } from 'react-router-dom'
import type {
  DiscrepancyNote,
  ExtractedConfig,
  InlineMemo,
} from '@/api/types'
import s from './HtmlView.module.css'

/** AI가 본문에서 뽑은 학습 설정 */
export function ConfigCard({
  data,
  onJump,
}: {
  data: ExtractedConfig
  onJump: (sectionId: string) => void
}) {
  return (
    <div className={s.card}>
      <div className={s.cardHead}>
        <span className={s.cardTitle}>{data.title}</span>
        <span className={s.cardCaption}>{data.caption}</span>
      </div>
      <div className={s.configList}>
        {data.rows.map((r) => (
          <Row key={r.label} label={r.label} value={r.value} ref_={r.ref} onJump={() => onJump(r.sectionId)} />
        ))}
      </div>
      <Link to="/experiments/new/from-paper" className={s.ref}>
        실험 설계 초안에 넣기
      </Link>
    </div>
  )
}

function Row({
  label,
  value,
  ref_,
  onJump,
}: {
  label: string
  value: string
  ref_: string
  onJump: () => void
}) {
  return (
    <>
      <span className={clsx(s.configCell, s.configLabel)}>{label}</span>
      <span className={s.configCell}>{value}</span>
      <span className={s.configCell}>
        <button type="button" onClick={onJump} className={s.ref}>
          {ref_}
        </button>
      </span>
    </>
  )
}

/** 본문과 표의 수치가 다를 때 */
export function CheckNote({
  data,
  target,
  onPick,
}: {
  data: DiscrepancyNote
  target: string | null
  onPick: (value: string) => void
}) {
  return (
    <div className={clsx(s.card, s.check)}>
      <span className={s.checkTitle}>{data.title}</span>
      <span className={s.checkText}>{data.text}</span>
      <div className={s.checkOptions}>
        {data.options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={target === o.value}
            onClick={() => onPick(o.value)}
            className={s.checkBtn}
          >
            {o.label}
          </button>
        ))}
        {target && (
          <span className={s.checkNote}>
            재현 목표를 {target}로 정했어요 · 요약 MD에도 남겼어요
          </span>
        )}
      </div>
    </div>
  )
}

/** 사용자가 남긴 메모 */
export function MemoCard({ data, onEdit }: { data: InlineMemo; onEdit: () => void }) {
  return (
    <div className={clsx(s.card, s.memo)}>
      <div className={s.memoHead}>
        <span className={s.memoTitle}>{data.title}</span>
        <span className={s.memoMeta}>{data.meta}</span>
        <button type="button" onClick={onEdit} className={clsx(s.ref, s.memoEdit)}>
          수정
        </button>
      </div>
      <span className={s.memoText}>{data.text}</span>
    </div>
  )
}
