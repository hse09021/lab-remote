import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { designDraftQuery } from '@/api/design'
import { ErrorState, LoadingState } from '@/components'
import s from './Mobile.module.css'

/**
 * 모바일 설계 초안 — 읽기 전용.
 * 값을 넣고 프로젝트를 만드는 건 PC에서 해요.
 */
export function MobileDesignDraft() {
  const [params] = useSearchParams()
  const paperId = params.get('paper') ?? 'attn'
  const draft = useQuery(designDraftQuery(paperId))

  if (draft.isPending) return <LoadingState label="설계 초안을 불러오는 중이에요…" />
  if (draft.isError || !draft.data) {
    return (
      <ErrorState
        title="설계 초안을 불러오지 못했어요"
        error={draft.error}
        onRetry={() => void draft.refetch()}
      />
    )
  }

  const data = draft.data
  const missing = data.values.filter(
    (v) => v.kind !== 'confirmed' && !(data.saved?.[v.key] ?? v.value ?? '').trim(),
  )

  return (
    <div className={s.page}>
      <div className={s.notice}>
        <span className={s.noticeTitle}>PC에서 열어 주세요</span>
        <p className={s.noticeText}>
          값을 넣고 프로젝트를 만드는 건 PC에서 해요. 여기서는 뽑아 둔 값만 확인할 수 있어요.
        </p>
      </div>

      <section className={s.card} aria-label="추출한 값">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>추출한 값</span>
          <span className={s.cardNote}>
            {data.values.length - missing.length} / {data.values.length} 채워짐
          </span>
        </div>
        <ul className={s.queue}>
          {data.values.map((v) => {
            const text = (data.saved?.[v.key] ?? v.value ?? '').trim()
            return (
              <li key={v.key} className={s.readRow}>
                <span className={s.readLabel}>{v.item}</span>
                <span className={s.readValue}>
                  {text || <span className={s.sheetNote}>아직 비어 있어요</span>}
                </span>
              </li>
            )
          })}
        </ul>
      </section>

      <section className={s.card} aria-label="실험 설계">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>실험 설계</span>
        </div>
        <ul className={s.queue}>
          {data.spec.map((row) => (
            <li key={row.label} className={s.readRow}>
              <span className={s.readLabel}>{row.label}</span>
              <span className={s.readValue}>{row.value}</span>
            </li>
          ))}
        </ul>
      </section>

      <p className={s.footNote}>기준 논문 · {data.paperTitle}</p>
    </div>
  )
}
