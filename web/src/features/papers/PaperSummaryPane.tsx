import type { ReactNode } from 'react'
import type { PaperSummary } from '@/api/types'
import { Button, SegmentedControl, VisuallyHidden } from '@/components'
import type { SegmentedItem } from '@/components'
import { buildSummaryMarkdown } from '@/lib/summaryMarkdown'
import s from './PaperSummaryPane.module.css'

export type SummaryView = 'nice' | 'raw'

const VIEW_ITEMS: SegmentedItem<SummaryView>[] = [
  { value: 'nice', label: '정리된 보기' },
  { value: 'raw', label: 'MD 원문' },
]

interface Props {
  summary: PaperSummary
  view: SummaryView
  onViewChange: (v: SummaryView) => void
  /** 지금 보여 줄 MD (저장된 값이나 수정 중인 글). 없으면 요약에서 만들어 써요 */
  draft: string | null
  /** 이미 저장된 MD. 이것과 다를 때만 "수정됨"이에요 */
  saved?: string | null
  onDraftChange: (text: string) => void
  onSave: () => void
  /** 근거 링크를 눌렀을 때. 리더에서는 해당 위치로 이동해요 */
  onJump?: (ref: string) => void
  /** 제목 옆·위에 붙일 것. 라이브러리는 "리더에서 열기" 버튼을 넣어요 */
  leadAction?: ReactNode
  /** textarea의 id. 한 화면에 두 번 쓰이면 달라야 해요 */
  textareaId?: string
}

/**
 * 요약 MD 패널. 라이브러리 드로어와 리더 AI 패널의 요약 탭이 같이 써요.
 * 목업에서는 두 화면에 같은 구조가 따로 들어 있었어요.
 */
export function PaperSummaryPane({
  summary,
  view,
  onViewChange,
  draft,
  saved = null,
  onDraftChange,
  onSave,
  onJump,
  leadAction,
  textareaId = 'summary-md',
}: Props) {
  const generated = buildSummaryMarkdown(summary)
  const text = draft ?? generated
  // 저장해 둔 값(없으면 요약에서 만든 값)과 다를 때만 저장할 게 있어요
  const base = saved ?? generated
  const dirty = draft !== null && draft !== base

  const Ref = ({ refText }: { refText: string }) =>
    onJump ? (
      <button type="button" onClick={() => onJump(refText)} className={s.ref}>
        근거
      </button>
    ) : (
      <span className={s.ref}>근거</span>
    )

  return (
    <div className={s.pane}>
      <div className={s.titleBlock}>
        <h2 className={s.title}>{summary.title}</h2>
        <span className={s.meta}>{summary.meta}</span>
      </div>

      <div className={s.actions}>
        {leadAction}
        <SegmentedControl
          items={VIEW_ITEMS}
          value={view}
          onChange={onViewChange}
          label="요약 보기 방식"
          size="sm"
          className={s.viewToggle}
        />
      </div>

      {view === 'raw' ? (
        <div className={s.rawBlock}>
          <VisuallyHidden>
            <label htmlFor={textareaId}>요약 MD 원문</label>
          </VisuallyHidden>
          <textarea
            id={textareaId}
            value={text}
            spellCheck={false}
            onChange={(e) => onDraftChange(e.target.value)}
            className={s.textarea}
          />
          <div className={s.saveRow}>
            <span data-dirty={dirty} className={s.mdStatus}>
              {dirty ? '수정됨 · 아직 저장하지 않았어요' : 'vault 파일과 동일해요'}
            </span>
            <Button variant="primary" size="sm" disabled={!dirty} onClick={onSave}>
              저장
            </Button>
          </div>
        </div>
      ) : (
        <div className={s.niceBlock}>
          <div className={s.group}>
            <span className={s.groupTitle}>3줄 요약</span>
            {summary.lines.map((l, i) => (
              <div key={i} className={s.line}>
                <span className={s.lineNo}>{i + 1}</span>
                <span>
                  {l.text} <Ref refText={l.ref} />
                </span>
              </div>
            ))}
          </div>

          <dl className={s.fields}>
            {summary.fields.map((f) => (
              <div key={f.label} style={{ display: 'contents' }}>
                <dt className={s.dt}>{f.label}</dt>
                <dd className={s.dd}>{f.value}</dd>
              </div>
            ))}
          </dl>

          <div className={s.section}>
            <span className={s.sectionLabel}>METHOD</span>
            <span className={s.sectionText}>
              {summary.method} <Ref refText="method" />
            </span>
          </div>
          <div className={s.section}>
            <span className={s.sectionLabel}>RESULT</span>
            <span className={s.sectionText}>
              {summary.result} <Ref refText="result" />
            </span>
          </div>
          <div className={s.section}>
            <span className={s.sectionLabel}>LIMITATION</span>
            <span className={`${s.sectionText} ${s.limitation}`}>{summary.limitation}</span>
          </div>
        </div>
      )}
    </div>
  )
}
