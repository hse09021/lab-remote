import { useState } from 'react'
import { usePopAt } from './usePopAt'
import type { Reference } from '@/api/types'
import { copyText } from '@/lib/clipboard'
import { referenceLinks } from '@/lib/referenceLinks'
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

  // arXiv · DOI · URL이 있으면 거기로, 없으면 제목으로 찾기
  const links = referenceLinks(r)
  const href = links.primary.href

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
        <a href={href} target="_blank" rel="noopener noreferrer" className={s.title} title={links.primary.label}>
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
        {r.arxiv && <span className={s.statePill}>arXiv:{r.arxiv}</span>}
      </div>

      {/* 인용된 자료 열기 — 새 탭으로 */}
      <div className={s.links}>
        {links.all.map((l) => (
          <a key={l.href} href={l.href} target="_blank" rel="noopener noreferrer" className={s.link}>
            {l.label} ↗
          </a>
        ))}
      </div>

      <p className={s.full}>
        [{r.n}] {r.authors}. {r.title}. {r.venue}, {r.year}.
      </p>

      {whyOpen && (
        <p className={s.why}>
          {r.why}
          {r.citedCount > 0 && ` · 본문에서 ${r.citedCount}번 인용했어요.`}
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
