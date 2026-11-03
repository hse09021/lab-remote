import type { CSSProperties, ReactNode } from 'react'
import type {
  Highlight,
  PaperReaderPayload,
  PaperSummary,
  Reference,
} from '@/api/types'
import { IconButton, SegmentedControl } from '@/components'
import type { SegmentedItem } from '@/components'
import { PaperSummaryPane } from '../PaperSummaryPane'
import type { SummaryView } from '../PaperSummaryPane'
import { HIGHLIGHT_CATEGORIES, type HighlightToggles } from './highlightCategories'
import s from './AiPanel.module.css'

export type AiTab = 'summary' | 'chat' | 'cite' | 'notes'

const TABS: SegmentedItem<AiTab>[] = [
  { value: 'summary', label: '요약' },
  { value: 'chat', label: '채팅' },
  { value: 'cite', label: '인용' },
  { value: 'notes', label: '노트' },
]

interface Props {
  style: CSSProperties
  onCollapse: () => void
  tab: AiTab
  onTabChange: (t: AiTab) => void
  reader: PaperReaderPayload
  summary: PaperSummary | undefined
  summaryView: SummaryView
  onSummaryViewChange: (v: SummaryView) => void
  mdDraft: string | null
  onMdDraftChange: (text: string) => void
  onMdSave: () => void
  /** 하이라이트 켜고 끈 상태 — 노트 탭도 같이 걸러져요 */
  toggles: HighlightToggles
  onJumpSection: (sectionId: string) => void
}

export function AiPanel({
  style,
  onCollapse,
  tab,
  onTabChange,
  reader,
  summary,
  summaryView,
  onSummaryViewChange,
  mdDraft,
  onMdDraftChange,
  onMdSave,
  toggles,
  onJumpSection,
}: Props) {
  return (
    <aside aria-label="AI 패널" style={style} className={s.panel}>
      <div className={s.head}>
        <IconButton label="AI 패널 접기" aria-expanded onClick={onCollapse}>
          <PanelIcon />
        </IconButton>
        <SegmentedControl
          items={TABS}
          value={tab}
          onChange={onTabChange}
          label="AI 패널"
          asTabs
          fill
          className={s.tabs}
        />
      </div>

      <div className={s.body}>
        {tab === 'summary' &&
          (summary ? (
            <div className={s.pad}>
              <PaperSummaryPane
                summary={summary}
                view={summaryView}
                onViewChange={onSummaryViewChange}
                draft={mdDraft}
                onDraftChange={onMdDraftChange}
                onSave={onMdSave}
                textareaId="reader-md"
                onJump={() => undefined}
              />
            </div>
          ) : (
            <p className={s.todo}>아직 요약이 없어요.</p>
          ))}

        {tab === 'chat' && (
          <p className={s.todo}>
            섹션 설명과 대화는 다음 단계에서 붙여요.
            <br />
            지금은 화면 틀만 있어요.
          </p>
        )}

        {tab === 'cite' && <CitationsTab reader={reader} />}

        {tab === 'notes' && (
          <NotesTab
            highlights={reader.highlights}
            sections={reader.sections}
            toggles={toggles}
            onJump={onJumpSection}
          />
        )}
      </div>
    </aside>
  )
}

/* ── 인용 ─────────────────────────────────────────────────── */

function CitationsTab({ reader }: { reader: PaperReaderPayload }) {
  // 본문에서 많이 인용된 순서, 같으면 번호 순
  const ranked = [...reader.references].sort(
    (a, b) => b.citedCount - a.citedCount || a.n - b.n,
  )

  return (
    <div className={s.pad}>
      <span className={s.caption}>{reader.citationsCaption}</span>
      {ranked.map((r) => (
        <RefRow key={r.n} r={r} />
      ))}
    </div>
  )
}

function RefRow({ r }: { r: Reference }) {
  const badge: { kind: 'in' | 'none'; label: string } = r.inLibrary
    ? { kind: 'in', label: '라이브러리' }
    : { kind: 'none', label: r.arxiv ? 'arXiv' : '없음' }

  return (
    <div className={s.refRow}>
      <span className={s.refNum}>[{r.n}]</span>
      <div className={s.refBody}>
        <button type="button" className={s.refTitle}>
          {r.title}
        </button>
        <span className={s.refMeta}>
          {r.short} · 본문 {r.citedCount}회
        </span>
      </div>
      <span data-kind={badge.kind} className={s.refBadge}>
        {badge.label}
      </span>
    </div>
  )
}

/* ── 노트 ─────────────────────────────────────────────────── */

function NotesTab({
  highlights,
  sections,
  toggles,
  onJump,
}: {
  highlights: Highlight[]
  sections: PaperReaderPayload['sections']
  toggles: HighlightToggles
  onJump: (id: string) => void
}) {
  const label = (cat: Highlight['category']) =>
    HIGHLIGHT_CATEGORIES.find((c) => c.id === cat)?.label ?? cat
  const sectionOf = (id: string) => sections.find((x) => x.id === id)

  const rows = highlights.filter((h) => toggles[h.category])

  return (
    <div className={s.pad}>
      <span className={s.caption}>
        하이라이트와 주석을 모아 둬요. 아웃라인에서 종류를 끄면 여기서도 숨겨져요.
      </span>
      {rows.length === 0 && <p className={s.todo}>켜 둔 종류의 하이라이트가 없어요.</p>}
      {rows.map((h) => {
        const sec = sectionOf(h.section)
        return (
          <div key={h.id} className={s.noteRow}>
            <span data-cat={h.category} className={s.notePill}>
              {label(h.category)}
            </span>
            <span className={s.noteText}>{h.note}</span>
            <button type="button" onClick={() => onJump(h.section)} className={s.noteWhere}>
              {sec?.n ? `§${sec.n}` : (sec?.title ?? h.section)} · p.{h.page}
            </button>
          </div>
        )
      })}
    </div>
  )
}

function PanelIcon(): ReactNode {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </svg>
  )
}
