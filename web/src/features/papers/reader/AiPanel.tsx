import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { runReaderAi, vaultQuery } from '@/api/papers'
import type { PaperAnalysis } from '@/api/papers'
import { CheckNote } from './html/blocks'
import { copyText } from '@/lib/clipboard'
import type { ExplainResult } from '@/api/papers'
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
  /** 요약 만들기 (실제 API 일 때만) */
  onMakeSummary?: () => void
  summaryRunning?: boolean
  /** AI 분석 — 하이라이트 구절 · 참고문헌 뽑기 (vault 논문) */
  onAnalyze?: () => void
  analyzing?: boolean
  analyzed?: boolean
  /** 채팅 탭을 실제 대화로 (vault 논문) */
  chatPaperId?: string
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
  /** AI 분석이 찾은 수치 불일치 — 노트 탭 맨 위에서 재현 목표를 골라요 */
  checks?: NonNullable<PaperAnalysis['discrepancies']>
  onPickTarget?: (index: number, value: string) => void
  /** 노트 탭의 "새 메모" — 지금 보는 섹션에 붙여요 */
  onAddNote?: (text: string) => void
  /** 지금 보는 섹션 (새 메모 위치) */
  currentLabel?: string
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
  onMakeSummary,
  summaryRunning = false,
  onAnalyze,
  analyzing = false,
  analyzed = false,
  chatPaperId,
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
  onAddNote,
  currentLabel = '',
  checks = [],
  onPickTarget,
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
      {onAnalyze && (
        <div className={s.analyzeBar}>
          <span>
            {analyzing
              ? 'Claude가 PDF를 읽고 하이라이트와 참고문헌을 뽑는 중이에요… (1~3분)'
              : analyzed
                ? 'AI 하이라이트와 참고문헌이 붙어 있어요'
                : 'AI 하이라이트와 인용 탭은 AI 분석을 하면 채워져요'}
          </span>
          {!analyzing && (
            <button type="button" className={s.analyzeBtn} onClick={onAnalyze}>
              {analyzed ? '다시 분석' : 'AI 분석'}
            </button>
          )}
        </div>
      )}

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
              <ObsidianLine path={summary.path} />
            </div>
          ) : (
            <div className={s.pad}>
              <p className={s.todo}>{summaryRunning ? 'Claude가 노트와 PDF를 읽고 요약하는 중이에요… (1~2분)' : '아직 요약이 없어요.'}</p>
              {onMakeSummary && !summaryRunning && (
                <button type="button" className={s.makeSummary} onClick={onMakeSummary}>
                  요약 만들기
                </button>
              )}
              {onMakeSummary && <p className={s.todo}>vault에 &lsquo;이름 요약.md&rsquo;를 새로 만들어요. 원래 노트는 고치지 않아요.</p>}
            </div>
          ))}

        {tab === 'chat' &&
          (chatPaperId ? (
            <PaperChat paperId={chatPaperId} context={chatContext} />
          ) : (
            <div className={s.pad}>
              {chatContext && <span className={s.contextChip}>{chatContext}</span>}
              <p className={s.todo}>
                섹션 설명은 본문의 AI 버튼을 누르면 떠 있는 대화창으로 열려요.
                <br />이 탭의 대화는 서버에 연결되면 이어져요.
              </p>
            </div>
          ))}

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
            onAdd={onAddNote}
            currentLabel={currentLabel}
            checks={checks}
            onPickTarget={onPickTarget}
            onAsk={chatPaperId ? () => onTabChange('chat') : undefined}
          />
        )}
      </div>
    </aside>
  )
}

/** "vault/Papers/X 요약.md 저장됨 · Obsidian 링크 복사" — Obsidian에서 바로 열리는 주소 */
function ObsidianLine({ path }: { path: string }) {
  const vault = useQuery(vaultQuery())
  const [copied, setCopied] = useState(false)
  if (!path) return null
  const rel = path.replace(/^vault\//, '').replace(/\.md$/, '')
  const name = (vault.data?.path ?? '').replace(/\/+$/, '').split('/').pop() ?? ''
  const link = `obsidian://open?vault=${encodeURIComponent(name)}&file=${encodeURIComponent(rel)}`
  return (
    <div className={s.obsidianLine}>
      <span className={s.obsidianPath}>{path} 저장됨</span>
      <button
        type="button"
        className={s.chatClear}
        disabled={!name}
        onClick={() => void copyText(link).then((ok) => setCopied(ok))}
      >
        {copied ? '복사했어요' : 'Obsidian 링크 복사'}
      </button>
    </div>
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
          {r.short}
          {r.citedCount > 0 && ` · 본문 ${r.citedCount}회`}
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
  onAdd,
  currentLabel,
  onAsk,
  checks,
  onPickTarget,
}: {
  checks: NonNullable<PaperAnalysis['discrepancies']>
  onPickTarget?: (index: number, value: string) => void
  onAdd?: (text: string) => void
  currentLabel: string
  onAsk?: () => void
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
  const [draft, setDraft] = useState('')

  return (
    <div className={s.pad}>
      <span className={s.caption}>
        AI 하이라이트와 내 메모예요. 누르면 해당 위치로 이동해요.
      </span>
      {/* 확인 필요 · 재현 목표 — AI 분석이 찾은, 본문과 표 · 그림이 다르게 적은 수치 */}
      {checks.map((c, i) => (
        <CheckNote
          key={`${c.title}-${i}`}
          data={{ title: `확인 필요 · ${c.title}${c.page ? ` · p.${c.page}` : ''}`, text: c.text, options: c.options, chosen: c.chosen }}
          target={c.chosen}
          onPick={(v) => onPickTarget?.(i, v)}
          savedNote={c.chosen ? `재현 목표: ${c.chosen}` : undefined}
        />
      ))}
      {onAdd && (
        // 새 메모 — 글자를 고르지 않고 지금 보는 섹션에 바로 남겨요
        <div className={s.newNote}>
          <span className={s.newNoteHead}>새 메모{currentLabel ? ` · ${currentLabel}` : ''}</span>
          <textarea
            className={s.newNoteInput}
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="이 섹션에 남길 메모"
            aria-label="새 메모"
          />
          <div className={s.newNoteActions}>
            <button
              type="button"
              className={s.analyzeBtn}
              disabled={!draft.trim()}
              onClick={() => {
                onAdd(draft.trim())
                setDraft('')
              }}
            >
              메모 저장
            </button>
            {onAsk && (
              <button type="button" className={s.chatClear} onClick={onAsk}>
                이 논문에 질문하기
              </button>
            )}
          </div>
        </div>
      )}
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

/** 채팅 탭 — 이 논문에 묻기 (Claude가 노트 · PDF를 읽기 전용으로). 대화는 저장하지 않아요 */
/**
 * "채팅" 탭 대화 — 탭을 옮기거나 패널을 접어도, 다른 논문에 갔다 와도 남아요(새로 고치면 비워져요).
 * 화면 밖 저장소에 두고, 답이 늦게 와도 그 논문 대화에 넣어요.
 */
type ChatTurn = { role: 'user' | 'assistant'; text: string }
const PAPER_CHATS = new Map<string, { log: ChatTurn[]; busy: boolean }>()
const chatListeners = new Set<() => void>()
const EMPTY_CHAT = { log: [] as ChatTurn[], busy: false }
function setPaperChat(id: string, fn: (c: { log: ChatTurn[]; busy: boolean }) => { log: ChatTurn[]; busy: boolean }) {
  PAPER_CHATS.set(id, fn(PAPER_CHATS.get(id) ?? EMPTY_CHAT))
  chatListeners.forEach((l) => l())
}
function usePaperChatStore(id: string) {
  return useSyncExternalStore(
    (l) => {
      chatListeners.add(l)
      return () => chatListeners.delete(l)
    },
    () => PAPER_CHATS.get(id) ?? EMPTY_CHAT,
  )
}

function PaperChat({ paperId, context }: { paperId: string; context: string | null }) {
  const { log, busy } = usePaperChatStore(paperId)
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  // 중괄호로 감싸요 — 요즘 Chrome의 scrollIntoView는 Promise를 돌려줘서, 그대로 돌려주면
  // React가 정리 함수로 알고 불러서 화면이 깨져요 ("destroy is not a function")
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [log.length, busy])
  const send = () => {
    const q = draft.trim()
    if (!q || busy) return
    const history = log
    setPaperChat(paperId, (c) => ({ log: [...c.log, { role: 'user', text: q }], busy: true }))
    setDraft('')
    const answer = (text: string) => setPaperChat(paperId, (c) => ({ log: [...c.log, { role: 'assistant', text }], busy: false }))
    runReaderAi<ExplainResult>(paperId, { kind: 'ask', question: q, history, text: context ?? '' })
      .then((r) => answer((r.paragraphs ?? []).join('\n\n') || r.title))
      .catch((e: unknown) => answer(`답하지 못했어요 — ${e instanceof Error ? e.message : String(e)}`))
  }
  return (
    <div className={s.chatTab}>
      <div className={s.chatLog}>
        {context && <span className={s.contextChip}>{context}</span>}
        {log.length === 0 && <p className={s.todo}>이 논문에 대해 물어보세요. 보내기를 누를 때만 Claude가 노트와 PDF를 읽고 답해요.</p>}
        {log.map((m, i) => (
          <div key={i} className={m.role === 'user' ? s.chatUser : s.chatAnswer}>
            {m.text}
          </div>
        ))}
        {busy && <div className={s.chatAnswer}>논문을 읽는 중이에요…</div>}
        {log.length > 0 && !busy && (
          <button type="button" className={s.chatClear} onClick={() => setPaperChat(paperId, () => EMPTY_CHAT)}>
            대화 지우기
          </button>
        )}
        <div ref={end} />
      </div>
      <div className={s.chatComposer}>
        <input
          className={s.chatInput}
          value={draft}
          placeholder="이 논문에 묻기"
          aria-label="이 논문에 묻기"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) send()
          }}
        />
        <button type="button" className={s.analyzeBtn} disabled={busy || !draft.trim()} onClick={send}>
          보내기
        </button>
      </div>
    </div>
  )
}
