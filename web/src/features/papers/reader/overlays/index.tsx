import clsx from 'clsx'
import type { CSSProperties } from 'react'
import type { ExplainZone, Highlight, PaperSection, PtRect } from '@/api/types'
import type { PdfPageContext } from '../pdf/types'
import { HIGHLIGHT_CATEGORIES } from '../highlightCategories'
import s from './Overlays.module.css'

const labelOf = (cat: Highlight['category']) =>
  HIGHLIGHT_CATEGORIES.find((c) => c.id === cat)?.label ?? cat

/** 카테고리별 색을 CSS 변수로 넘겨요 (tokens.css 의 --hl-* 를 가리켜요) */
const catVars = (cat: Highlight['category']): CSSProperties =>
  ({
    '--hl-rgb': `var(--hl-${cat}-rgb)`,
    '--hl-ink': `var(--hl-${cat}-ink)`,
    '--hl-tint': `var(--hl-${cat}-tint)`,
  }) as CSSProperties

/* ── AI 하이라이트 ────────────────────────────────────────── */

export function HighlightOverlays({
  ctx,
  highlights,
  selectedId,
  onSelect,
}: {
  ctx: PdfPageContext
  highlights: Highlight[]
  selectedId: string | null
  onSelect: (h: Highlight) => void
}) {
  return (
    <>
      {highlights.flatMap((h) =>
        h.boxes.map((box: PtRect, i: number) => (
          <button
            key={`${h.id}-${i}`}
            type="button"
            aria-pressed={h.id === selectedId}
            aria-label={`${labelOf(h.category)} · ${h.note}`}
            onClick={() => onSelect(h)}
            style={{ ...ctx.rectToStyle(box), ...catVars(h.category) }}
            className={s.highlight}
          />
        )),
      )}
    </>
  )
}

/* ── 하이라이트 메모 카드 ─────────────────────────────────── */

export function HighlightMemo({
  ctx,
  highlight,
  pageHeight,
  pageWidth,
  onAsk,
  onOpenHtml,
  onClose,
}: {
  ctx: PdfPageContext
  highlight: Highlight
  pageHeight: number
  pageWidth: number
  onAsk: () => void
  onOpenHtml: () => void
  onClose: () => void
}) {
  const first = highlight.boxes[0]!
  const last = highlight.boxes[highlight.boxes.length - 1]!
  // 쪽 아래쪽이면 위로 띄워요 (목업과 같은 기준)
  const below = last[3] / pageHeight < 0.78

  const style: CSSProperties = {
    ...catVars(highlight.category),
    left: `${Math.min((first[0] / pageWidth) * 100, 46)}%`,
    ...(below
      ? { top: `calc(${(last[3] / pageHeight) * 100}% + 8px)` }
      : { bottom: `calc(${100 - (first[1] / pageHeight) * 100}% + 8px)` }),
  }

  return (
    <div
      role="dialog"
      aria-label={`${labelOf(highlight.category)} 메모`}
      style={style}
      className={s.memo}
      data-page={ctx.page}
    >
      <span className={s.memoPill}>{labelOf(highlight.category)}</span>
      <span className={s.memoNote}>{highlight.note}</span>
      <div className={s.memoActions}>
        <button type="button" onClick={onAsk} className={clsx(s.memoBtn, s.memoPrimary)}>
          채팅에 묻기
        </button>
        <button
          type="button"
          onClick={onOpenHtml}
          className={clsx(s.memoBtn, s.memoOutline)}
        >
          HTML에서 보기
        </button>
        <button type="button" onClick={onClose} className={clsx(s.memoBtn, s.memoClose)}>
          닫기
        </button>
      </div>
    </div>
  )
}

/* ── 섹션 설명 버튼 ───────────────────────────────────────── */

export function SectionSparkles({
  ctx,
  sections,
  titleSpot,
  onExplain,
}: {
  ctx: PdfPageContext
  sections: PaperSection[]
  /** 1쪽 제목 옆 버튼 */
  titleSpot: { x: number; y: number } | null
  onExplain: (key: string) => void
}) {
  const spark = (key: string, label: string, x: number, y: number) => (
    <button
      key={key}
      type="button"
      aria-label={label}
      onClick={() => onExplain(key)}
      style={ctx.pointToStyle(x, y)}
      className={s.sparkle}
    >
      <SparkIcon />
      <span className={s.tip}>
        설명 <span className={s.kbd}>E</span>
      </span>
    </button>
  )

  return (
    <>
      {titleSpot && spark('title', '논문 전체 설명받기', titleSpot.x, titleSpot.y)}
      {sections.map((sec) =>
        spark(
          sec.id,
          `${sec.n ? sec.n + ' ' : ''}${sec.title} 설명받기`,
          sec.xEnd + 8,
          sec.y + 6,
        ),
      )}
    </>
  )
}

/* ── 그림·수식 영역 ───────────────────────────────────────── */

export function ExplainZones({
  ctx,
  zones,
  onExplain,
  onCopy,
}: {
  ctx: PdfPageContext
  zones: ExplainZone[]
  onExplain: (key: string) => void
  onCopy: (zone: ExplainZone) => void
}) {
  return (
    <>
      {zones.map((z) => (
        <div key={z.key} style={ctx.rectToStyle(z.box)} className={s.zone}>
          <div data-placement={z.barPlacement} className={s.zoneBar}>
            <button type="button" onClick={() => onExplain(z.key)} className={s.zoneBtn}>
              {z.kind === 'fig'
                ? '이 그림(figure) 풀어서 설명받기'
                : '이 수식 풀어서 설명받기'}
            </button>
            <button
              type="button"
              aria-label={z.kind === 'fig' ? '그림 복사' : 'LaTeX 복사'}
              title={z.kind === 'fig' ? '그림 복사' : 'LaTeX 복사'}
              onClick={() => onCopy(z)}
              className={s.zoneIcon}
            >
              <CopyIcon />
            </button>
          </div>
        </div>
      ))}
    </>
  )
}

/* ── 인용 핫스팟 ──────────────────────────────────────────── */

export function CiteHotspots({
  ctx,
  spots,
}: {
  ctx: PdfPageContext
  spots: Array<{ n: number; box: PtRect }>
}) {
  return (
    <>
      {spots.map((spot, i) => (
        <button
          key={`${spot.n}-${i}`}
          type="button"
          // 인용 카드는 리더 4에서 붙여요. 지금은 올리면 강조만 해요
          aria-label={`참고문헌 ${spot.n}번`}
          title={`참고문헌 ${spot.n}번`}
          style={ctx.rectToStyle(spot.box)}
          className={s.cite}
        />
      ))}
    </>
  )
}

/* ── 섹션 위치 표식 ───────────────────────────────────────── */

export function SectionMarkers({
  sections,
  pageHeight,
  onMarker,
}: {
  sections: PaperSection[]
  pageHeight: number
  onMarker: (sectionId: string, el: HTMLElement | null) => void
}) {
  return (
    <>
      {sections.map((sec) => (
        <span
          key={sec.id}
          ref={(el) => onMarker(sec.id, el)}
          data-section={sec.id}
          aria-hidden="true"
          style={{ top: `${(sec.y / pageHeight) * 100}%` }}
          className={s.marker}
        />
      ))}
    </>
  )
}

/* ── 아이콘 ───────────────────────────────────────────────── */

const SparkIcon = () => (
  <svg
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16l-1.8-4.5L5 9.7l5.2-1.8z" />
    <path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z" />
  </svg>
)

const CopyIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1" />
  </svg>
)
