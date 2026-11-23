import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { annotationsQuery, useRestoreAnnotation, useUpdateAnnotation } from '@/api/annotations'
import clsx from 'clsx'
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
/** 고친 인라인 메모의 주석 id — 논문마다 하나 */
const MEMO_ID = 'memo-inline'

export function MemoCard({ data, paperId }: { data: InlineMemo; paperId: string }) {
  // 고친 메모는 내 주석 저장소에 같은 id로 남겨요 (기기끼리 같이 봐요)
  const notes = useQuery(annotationsQuery(paperId))
  // 정해 둔 id로 만들어요 (되돌리기와 같은 길 — id 를 그대로 넘겨요)
  const add = useRestoreAnnotation(paperId)
  const update = useUpdateAnnotation(paperId)
  const saved = notes.data?.find((a) => a.id === MEMO_ID)
  const text = saved?.text ?? data.text
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const save = () => {
    const next = draft.trim()
    if (!next) return
    if (saved) update.mutate({ id: MEMO_ID, text: next }, { onSuccess: () => setEditing(false) })
    else
      add.mutate(
        { id: MEMO_ID, paperId, kind: 'note', text: next, source: data.title, sectionId: 'memo', page: 0, anchor: null, boxes: null, createdAt: Date.now() },
        { onSuccess: () => setEditing(false) },
      )
  }
  return (
    <div className={clsx(s.card, s.memo)}>
      <div className={s.memoHead}>
        <span className={s.memoTitle}>{data.title}</span>
        <span className={s.memoMeta}>{data.meta}</span>
        {!editing && (
          <button
            type="button"
            onClick={() => {
              setDraft(text)
              setEditing(true)
            }}
            className={clsx(s.ref, s.memoEdit)}
          >
            수정
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea className={s.memoInput} value={draft} onChange={(e) => setDraft(e.target.value)} rows={4} autoFocus aria-label="메모 고치기" />
          <div className={s.memoActions}>
            <button type="button" className={s.ref} onClick={() => setEditing(false)}>
              취소
            </button>
            <button type="button" className={s.ref} disabled={add.isPending || update.isPending || !draft.trim()} onClick={save}>
              저장
            </button>
          </div>
        </>
      ) : (
        <span className={s.memoText}>{text}</span>
      )}
    </div>
  )
}
