import { useState } from 'react'
import type { ReactNode } from 'react'
import { usePopAt } from './usePopAt'
import { Button } from '@/components'
import s from './SelectionMenu.module.css'

export type SelectionAction = 'explain' | 'info' | 'highlight' | 'translate' | 'note' | 'ask'

export interface SelectionAnchor {
  x: number
  y: number
  width: number
}

/** 단축키 — 목업과 같아요 */
export const SELECTION_KEYS: Record<string, SelectionAction> = {
  e: 'explain',
  i: 'info',
  h: 'highlight',
  t: 'translate',
  c: 'note',
  enter: 'ask',
}

interface Props {
  anchor: SelectionAnchor
  /** 이미 내 하이라이트를 쳤는지 */
  highlighted: boolean
  onAct: (a: SelectionAction) => void
}

export function SelectionMenu({ anchor, highlighted, onAct }: Props) {
  const [infoHover, setInfoHover] = useState(false)

  const items: Array<{
    id: SelectionAction
    label: string
    key: string
    icon: ReactNode
    badge?: string
    swatch?: boolean
  }> = [
    { id: 'explain', label: '설명', key: 'E', icon: <SparkIcon /> },
    { id: 'info', label: '인포그래픽', key: 'I', icon: <ChartIcon />, badge: 'NEW' },
    {
      id: 'highlight',
      label: highlighted ? '하이라이트 삭제' : '하이라이트',
      key: 'H',
      icon: <PenIcon />,
      swatch: true,
    },
    { id: 'translate', label: '번역', key: 'T', icon: <GlobeIcon /> },
    { id: 'note', label: '주석', key: 'C', icon: <NoteIcon /> },
    { id: 'ask', label: 'AI에게 질문', key: 'Enter', icon: <AskIcon /> },
  ]

  const { ref, style, left, avail } = usePopAt(anchor.x, anchor.y, 360)
  // 목업 infoLeft — 오른쪽에 자리가 있으면 옆에, 없으면 왼쪽에
  const previewLeft =
    avail !== null && left + 360 + 12 + 380 <= avail ? left + 372 : Math.max(12, left - 392)

  return (
    <>
      <div
        ref={ref}
        role="menu"
        aria-label="선택한 텍스트"
        data-reader-overlay=""
        style={style}
        className={s.menu}
      >
        {items.map((it) => (
          <button
            key={it.id}
            type="button"
            role="menuitem"
            onClick={() => onAct(it.id)}
            onMouseEnter={() => it.id === 'info' && setInfoHover(true)}
            onMouseLeave={() => it.id === 'info' && setInfoHover(false)}
            className={s.item}
          >
            {it.icon}
            <span className={s.label}>{it.label}</span>
            {it.swatch && <span aria-hidden="true" className={s.swatch} />}
            {it.badge && <span className={s.badge}>{it.badge}</span>}
            <span aria-hidden="true" className={s.key}>
              {it.key}
            </span>
          </button>
        ))}
      </div>

      {/* 인포그래픽에 마우스를 올리면 옆에 미리보기 */}
      {infoHover && (
        <div
          style={{ left: previewLeft, top: anchor.y + 8 }}
          data-reader-overlay=""
          className={s.preview}
          aria-hidden="true"
        >
          <span className={s.previewTitle}>인포그래픽 미리보기</span>
          <div className={s.previewBars}>
            {[92, 70, 84, 58].map((w) => (
              <div key={w} style={{ width: `${w}%` }} className={s.previewBar} />
            ))}
          </div>
          <span className={s.previewNote}>
            선택한 부분을 흐름도로 만들어 vault에 저장해요. 지금은 미리보기만 볼 수 있어요.
          </span>
        </div>
      )}
    </>
  )
}

/* ── 번역 팝오버 ──────────────────────────────────────────── */

export function TranslatePopover({
  anchor,
  source,
  translation,
  note,
  onClose,
}: {
  anchor: SelectionAnchor
  source: string
  /** 미리 써 둔 번역이 없는 글은 자리표시로 둬요 (지어내지 않아요) */
  translation: string | null
  note: string | null
  onClose: () => void
}) {
  const { ref, style } = usePopAt(anchor.x, anchor.y, 340)
  return (
    <div
      role="dialog"
      aria-label="번역"
      ref={ref}
      style={style}
      data-reader-overlay=""
      className={s.popover}
    >
      <span className={s.popTitle}>번역</span>
      <span className={s.popSource}>{source}</span>
      <span className={s.popText}>{translation ?? '[번역 결과]'}</span>
      {note && <span className={s.previewNote}>{note}</span>}
      <div className={s.popActions}>
        <Button size="sm" onClick={onClose}>
          닫기
        </Button>
      </div>
    </div>
  )
}

/* ── 주석 팝오버 ──────────────────────────────────────────── */

export function NotePopover({
  anchor,
  onSave,
  onClose,
}: {
  anchor: SelectionAnchor
  onSave: (text: string) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState('')
  const { ref, style } = usePopAt(anchor.x, anchor.y, 340)
  return (
    <div
      role="dialog"
      aria-label="주석 남기기"
      ref={ref}
      style={style}
      data-reader-overlay=""
      className={s.popover}
    >
      <span className={s.popTitle}>주석</span>
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="이 부분에 대한 주석을 입력하세요"
        aria-label="주석 내용"
        className={s.popArea}
      />
      <div className={s.popActions}>
        <Button size="sm" onClick={onClose}>
          취소
        </Button>
        <Button variant="primary" size="sm" onClick={() => onSave(draft.trim() || '(빈 주석)')}>
          저장
        </Button>
      </div>
    </div>
  )
}

/* ── 메뉴 아이콘 (목업 FocusReader의 svg 그대로) ─────────── */

function Svg({ children, round }: { children: ReactNode; round?: boolean }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin={round ? 'round' : undefined}
      aria-hidden="true"
      className={s.icon}
    >
      {children}
    </svg>
  )
}

function SparkIcon() {
  return (
    <Svg round>
      <path d="M4 8V5a1 1 0 011-1h3M16 4h3a1 1 0 011 1v3M20 16v3a1 1 0 01-1 1h-3M8 20H5a1 1 0 01-1-1v-3" />
      <path d="M12 7.5l1.2 3.3 3.3 1.2-3.3 1.2L12 16.5l-1.2-3.3L7.5 12l3.3-1.2z" fill="currentColor" stroke="none" />
    </Svg>
  )
}

function ChartIcon() {
  return (
    <Svg>
      <path d="M4 6h3M4 12h3M4 18h3M10 6h10M10 12h7M10 18h9" />
    </Svg>
  )
}

function PenIcon() {
  return (
    <Svg round>
      <path d="M14 4l6 6-9 9H5v-6z" />
      <path d="M3 21h8" />
    </Svg>
  )
}

function GlobeIcon() {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18" />
    </Svg>
  )
}

function NoteIcon() {
  return (
    <Svg round>
      <path d="M5 5h14v10H9l-4 4z" />
    </Svg>
  )
}

function AskIcon() {
  return (
    <Svg round>
      <path d="M4 5h11v8H8l-4 3z" />
      <path d="M15 9h5v8l-3-2h-6v-2" />
    </Svg>
  )
}
