import { useState } from 'react'
import { usePopAt } from './usePopAt'
import type { Reference } from '@/api/types'
import { copyText } from '@/lib/clipboard'
import s from './CiteCard.module.css'

export interface CiteAnchor {
  x: number
  y: number
  width: number
}

interface Props {
  reference: Reference
  anchor: CiteAnchor
  /** 라이브러리에 보관했는지 */
  saved: boolean
  onSave: () => void
  onClose: () => void
  /** 읽을 가치 알아보기 → 대화창 */
  onWorth: () => void
  onToast: (msg: string) => void
}

export function CiteCard({
  reference: r,
  anchor,
  saved,
  onSave,
  onClose,
  onWorth,
  onToast,
}: Props) {
  const [whyOpen, setWhyOpen] = useState(false)

  const href = r.arxiv
    ? `https://arxiv.org/abs/${r.arxiv}`
    : `https://scholar.google.com/scholar?q=${encodeURIComponent(r.title)}`

  const bibtex = [
    `@article{ref${r.n},`,
    `  title   = {${r.title}},`,
    `  author  = {${r.authors}},`,
    `  journal = {${r.venue}},`,
    `  year    = {${r.year}}`,
    `}`,
  ].join('\n')

  // 목업 popAt — 보이는 폭 밖으로 넘치지 않게 묶어요
  const { ref, style } = usePopAt(anchor.x, anchor.y, 540, 10)

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`참고문헌 ${r.n}번`}
      style={style}
      data-reader-overlay=""
      className={s.card}
    >
      <div className={s.head}>
        <a href={href} target="_blank" rel="noopener" className={s.title}>
          {r.title}
        </a>
      </div>
      <span className={s.authors}>{r.authors}</span>
      <span className={s.venue}>
        {r.venue} · {r.year}
      </span>

      <div className={s.pills}>
        <button
          type="button"
          aria-pressed={saved || r.inLibrary}
          onClick={onSave}
          className={s.savePill}
        >
          {r.inLibrary ? '라이브러리에 있어요' : saved ? '보관했어요' : '라이브러리에 보관'}
        </button>
        <span className={s.statePill}>
          {r.arxiv ? `arXiv:${r.arxiv}` : '원문 링크 없음'}
        </span>
        {/* 실제 값은 Semantic Scholar 에서 받아요 */}
        <span className={s.cited}>피인용 [Semantic Scholar 값]</span>
      </div>

      <p className={s.full}>
        [{r.n}] {r.authors}. {r.title}. {r.venue}, {r.year}.
      </p>

      {whyOpen && (
        <p className={s.why}>
          {r.why} · 본문에서 {r.citedCount}번 인용했어요.
        </p>
      )}

      <span className={s.disclaimer}>*이 정보는 바뀌거나 정확하지 않을 수 있어요.</span>

      <div className={s.actions}>
        <button type="button" onClick={() => setWhyOpen((v) => !v)} className={s.action}>
          인용 이유 {whyOpen ? '접기' : '펼치기'}
        </button>
        <button type="button" onClick={onWorth} className={s.action}>
          읽을 가치 알아보기
        </button>
        <button
          type="button"
          onClick={async () => {
            await copyText(bibtex)
            onToast('BibTeX를 복사했어요')
          }}
          className={s.action}
        >
          BibTeX 복사
        </button>
        <button type="button" onClick={onClose} className={`${s.action} ${s.close}`}>
          닫기
        </button>
      </div>
    </div>
  )
}
