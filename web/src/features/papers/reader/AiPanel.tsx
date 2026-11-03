import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import type { UserAnnotation } from '@/api/annotations'
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
  /** 이미 저장된 MD — "수정됨" 판정 기준 */
  mdSaved: string | null
  onMdDraftChange: (text: string) => void
  onMdSave: () => void
  /** 하이라이트 켜고 끈 상태 — 노트 탭도 같이 걸러져요 */
  toggles: HighlightToggles
  onJumpSection: (sectionId: string) => void
  /** 채팅 탭 위에 붙는 맥락 칩 */
  chatContext: string | null
  /** 사용자가 직접 친 하이라이트·주석 */
  userNotes: UserAnnotation[]
  /** 위치 표기 — 번호 없는 섹션은 § 없이 */
  sectionLabel: (sectionId: string) => string
  onEditNote: (annotation: UserAnnotation, text: string) => void
  onDeleteNote: (annotation: UserAnnotation) => void
  /** 인용 카드로 보관한 참고문헌인지 — 라이브러리 캐시에서 봐요 */
  isRefSaved: (r: { n: number; arxiv: string | null }) => boolean
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
  mdSaved,
  onMdDraftChange,
  onMdSave,
  toggles,
  onJumpSection,
  chatContext,
  userNotes,
  sectionLabel,
  onEditNote,
  onDeleteNote,
  isRefSaved,
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
                saved={mdSaved}
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
          <div className={s.pad}>
            {chatContext && <span className={s.contextChip}>{chatContext}</span>}
            <p className={s.todo}>
              섹션 설명은 본문의 AI 버튼을 누르면 떠 있는 대화창으로 열려요.
              <br />이 탭의 대화는 서버가 붙으면 이어져요.
            </p>
          </div>
        )}

        {tab === 'cite' && <CitationsTab reader={reader} isRefSaved={isRefSaved} />}

        {tab === 'notes' && (
          <NotesTab
            highlights={reader.highlights}
            sections={reader.sections}
            toggles={toggles}
            onJump={onJumpSection}
            userNotes={userNotes}
            label={sectionLabel}
            onEdit={onEditNote}
            onDelete={onDeleteNote}
          />
        )}
      </div>
    </aside>
  )
}

/* ── 인용 ─────────────────────────────────────────────────── */

function CitationsTab({
  reader,
  isRefSaved,
}: {
  reader: PaperReaderPayload
  isRefSaved: (r: { n: number; arxiv: string | null }) => boolean
}) {
  // 본문에서 많이 인용된 순서, 같으면 번호 순
  const ranked = [...reader.references].sort(
    (a, b) => b.citedCount - a.citedCount || a.n - b.n,
  )

  return (
    <div className={s.pad}>
      <span className={s.caption}>{reader.citationsCaption}</span>
      {ranked.map((r) => (
        <RefRow key={r.n} r={r} added={isRefSaved(r)} />
      ))}
    </div>
  )
}

function RefRow({ r, added }: { r: Reference; added: boolean }) {
  const badge: { kind: 'in' | 'none'; label: string } = added
    ? { kind: 'in', label: '추가됨' }
    : r.inLibrary
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
  userNotes,
  label: locationLabel,
  onEdit,
  onDelete,
}: {
  highlights: Highlight[]
  sections: PaperReaderPayload['sections']
  toggles: HighlightToggles
  onJump: (id: string) => void
  userNotes: UserAnnotation[]
  /** 위치 표기 — 번호 없는 섹션은 § 없이 */
  label: (sectionId: string) => string
  onEdit: (annotation: UserAnnotation, text: string) => void
  onDelete: (annotation: UserAnnotation) => void
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
      {userNotes.map((n) => (
        <MyNoteRow
          key={n.id}
          annotation={n}
          where={locationLabel(n.sectionId)}
          onJump={() => onJump(n.sectionId)}
          onEdit={(text) => onEdit(n, text)}
          onDelete={() => onDelete(n)}
        />
      ))}
      {rows.length === 0 && userNotes.length === 0 && (
        <p className={s.todo}>켜 둔 종류의 하이라이트가 없어요.</p>
      )}
      {rows.map((h) => {
        const sec = sectionOf(h.section)
        return (
          <div key={h.id} className={s.noteRow}>
            <span data-cat={h.category} className={s.notePill}>
              {label(h.category)}
            </span>
            <span className={s.noteText}>{h.note}</span>
            <div className={s.noteFoot}>
              <button type="button" onClick={() => onJump(h.section)} className={s.noteWhere}>
                {sec?.n ? `§${sec.n}` : (sec?.title ?? h.section)} · p.{h.page}
              </button>
            </div>
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

/**
 * 노트 탭의 내 항목 한 줄.
 * 마우스를 올리거나 키보드로 들어오면 수정(주석만)·삭제 버튼이 보여요.
 */
function MyNoteRow({
  annotation,
  where,
  onJump,
  onEdit,
  onDelete,
}: {
  annotation: UserAnnotation
  where: string
  onJump: () => void
  onEdit: (text: string) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(annotation.text)
  const isNote = annotation.kind === 'note'

  if (editing) {
    return (
      <div className={s.noteRow}>
        <span data-cat="memo" className={s.notePill}>
          주석
        </span>
        <textarea
          autoFocus
          aria-label="주석 고치기"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setEditing(false)
          }}
          className={s.noteEdit}
        />
        <div className={s.noteFoot}>
          <span className={s.noteWhereStatic}>고치는 중</span>
          <div className={s.noteToolsOpen}>
            <button
              type="button"
              onClick={() => {
                const text = draft.trim()
                if (text) onEdit(text)
                setEditing(false)
              }}
              className={s.noteTool}
            >
              저장
            </button>
            <button type="button" onClick={() => setEditing(false)} className={s.noteTool}>
              취소
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={s.noteRow}>
      <span data-cat="memo" className={s.notePill}>
        {isNote ? '주석' : '내 하이라이트'}
      </span>
      <span className={s.noteText}>{annotation.text}</span>
      <div className={s.noteFoot}>
        <button type="button" onClick={onJump} className={s.noteWhere}>
          {where}
        </button>
        {/* 자리는 늘 잡아 두고 보이기만 바꿔요 — 줄 높이가 흔들리지 않게 */}
        <div className={s.noteTools}>
          {isNote && (
            <button
              type="button"
              aria-label="주석 고치기"
              onClick={() => {
                setDraft(annotation.text)
                setEditing(true)
              }}
              className={s.noteTool}
            >
              수정
            </button>
          )}
          <button
            type="button"
            aria-label={isNote ? '주석 삭제' : '하이라이트 삭제'}
            onClick={onDelete}
            className={`${s.noteTool} ${s.noteToolDanger}`}
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  )
}
