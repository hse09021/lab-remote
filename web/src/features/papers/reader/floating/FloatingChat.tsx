import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties, KeyboardEvent, PointerEvent, ReactNode, RefObject } from 'react'
import type { Topic, TopicBlock } from '@/api/types'
import { IconButton } from '@/components'
import type { ChatAnchor, FloatingChatState } from './useFloatingChat'
import s from './FloatingChat.module.css'

const MIN_W = 380
const MAX_W = 760
const MIN_H = 320
const MAX_H = 860

interface Props {
  state: FloatingChatState
  topic: Topic | undefined
  terms: Record<string, string>
  onClose: () => void
  onClear: () => void
  onMinimize: () => void
  onRestore: () => void
  onAsk: (q: string, canned?: { a: string; go: string; src: string }) => void
  /** 근거 링크를 눌렀을 때 본문 이동 */
  onJump: (sectionId: string) => void
  /** 관련 논문 */
  onOpenPaper: (title: string) => void
  /** 대화창 본체를 띄울 곳 (스크롤하지 않는 가운데 열) */
  host: RefObject<HTMLElement | null>
}

export function FloatingChat({
  host,
  state,
  topic,
  terms,
  onClose,
  onClear,
  onMinimize,
  onRestore,
  onAsk,
  onJump,
  onOpenPaper,
}: Props) {
  const [size, setSize] = useState({ w: 540, h: 600 })
  const drag = useRef<{ x: number; y: number; w: number; h: number } | null>(null)
  /** 가운데 열의 보이는 높이 — 툴바 밑으로 잘리지 않게 여기에 맞춰 묶어요 */
  const [maxH, setMaxH] = useState(MAX_H)

  useEffect(() => {
    const el = host.current
    if (!el) return
    const measure = () => setMaxH(Math.max(MIN_H, Math.min(MAX_H, el.clientHeight - 40)))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [host, state.open])

  useEffect(() => {
    const onMove = (e: globalThis.PointerEvent) => {
      const d = drag.current
      if (!d) return
      // 왼쪽 위 모서리를 잡고 끌면 커져요
      const w = Math.min(MAX_W, Math.max(MIN_W, d.w - (e.clientX - d.x)))
      const h = Math.min(maxH, Math.max(MIN_H, d.h - (e.clientY - d.y)))
      setSize({ w, h })
    }
    const onUp = () => {
      drag.current = null
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [maxH])

  if (!state.open) return null

  // 최소화하면 연 자리 바로 아래 알약으로 (본문 스크롤을 따라가요)
  if (state.minimized) {
    return (
      <button
        type="button"
        aria-label={`${topic?.title ?? '설명'} 대화창 펼치기`}
        onClick={onRestore}
        style={pillStyle(state.anchor)}
        className={s.pill}
      >
        <SparkIcon />
        <span className={s.pillText}>{topic?.title ?? '설명'}</span>
      </button>
    )
  }

  const onGrip = (e: PointerEvent<HTMLButtonElement>) => {
    e.preventDefault()
    drag.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h }
  }

  const win = (
    <section
      aria-label={topic?.title ?? '설명'}
      style={{ width: size.w, height: Math.min(size.h, maxH), right: 20, bottom: 20 }}
      className={s.window}
    >
      <button
        type="button"
        aria-label="대화창 크기 조절"
        onPointerDown={onGrip}
        className={s.grip}
      />

      <div className={s.head}>
        <SparkIcon />
        <span className={s.title}>{topic?.title ?? '설명'}</span>
        <IconButton label="대화 지우기" size={34} onClick={onClear}>
          <TrashIcon />
        </IconButton>
        <IconButton label="대화창 접기" size={34} onClick={onMinimize}>
          <MinusIcon />
        </IconButton>
        <IconButton label="대화창 닫기" size={34} onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>

      <div className={s.body}>
        {state.context && <span className={s.context}>{state.context}</span>}
        {topic?.quote && <p className={s.quote}>{topic.quote}</p>}

        {topic?.blocks.map((b, i) => (
          <Block key={i} block={b} terms={terms} onJump={onJump} onOpenPaper={onOpenPaper} />
        ))}

        {topic?.qs.map((q) => (
          <button
            key={q.q}
            type="button"
            disabled={!!state.asked[q.q]}
            onClick={() => onAsk(q.q, { a: q.a, go: q.go, src: q.src })}
            className={s.question}
          >
            <BubbleIcon />
            <span>{q.q}</span>
          </button>
        ))}

        {state.log.map((e, i) => {
          if (e.kind === 'user') return <div key={i} className={s.userBubble}>{e.text}</div>
          if (e.kind === 'loading')
            return (
              <div key={i} className={s.skeletonRow}>
                {[92, 78, 54].map((w) => (
                  <div key={w} style={{ width: `${w}%` }} className={s.skeletonBar} />
                ))}
              </div>
            )
          return (
            <div key={i} className={s.para}>
              <Segments text={e.text} terms={terms} />
              {e.go && e.src && (
                <>
                  {' '}
                  <button type="button" onClick={() => onJump(e.go!)} className={s.source}>
                    {e.src}
                  </button>
                </>
              )}
            </div>
          )
        })}
      </div>

      <Composer onSend={(t) => onAsk(t)} />
    </section>
  )

  // 목업처럼 가운데 열 모서리에 붙여요 (본문 스크롤과 함께 움직이지 않아요)
  return host.current ? createPortal(win, host.current) : win
}

function Composer({ onSend }: { onSend: (text: string) => void }) {
  const [draft, setDraft] = useState('')
  const send = () => {
    const t = draft.trim()
    if (!t) return
    onSend(t)
    setDraft('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }
  return (
    <div className={s.footer}>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="이어서 궁금한 점을 물어보세요."
        aria-label="이어서 질문하기"
        className={s.input}
      />
      <button type="button" aria-label="보내기" onClick={send} className={s.send}>
        <ArrowUpIcon />
      </button>
    </div>
  )
}

/* ── 블록 ─────────────────────────────────────────────────── */

function Block({
  block,
  terms,
  onJump,
  onOpenPaper,
}: {
  block: TopicBlock
  terms: Record<string, string>
  onJump: (id: string) => void
  onOpenPaper: (title: string) => void
}): ReactNode {
  if ('h' in block) return <h3 className={s.h3}>{block.h}</h3>
  if ('li' in block)
    return (
      <div className={s.listItem}>
        <span aria-hidden="true" className={s.bullet}>
          •
        </span>
        <span>
          <span className={s.lead}>{block.li}</span> <Segments text={block.p} terms={terms} />
        </span>
      </div>
    )
  if ('rel' in block)
    return (
      <div className={s.related}>
        <button type="button" onClick={() => onOpenPaper(block.rel)} className={s.relatedTitle}>
          {block.rel}
        </button>
        <span className={s.relatedNote}>{block.note}</span>
      </div>
    )
  if ('src' in block)
    return (
      <button type="button" onClick={() => onJump(block.go)} className={s.source}>
        {block.src}
      </button>
    )
  if ('info' in block) return <InfoGraphic />
  return (
    <p className={s.para}>
      <Segments text={block.p} terms={terms} />
    </p>
  )
}

/** [[용어]] 를 점선 밑줄 + 뜻 툴팁으로 바꿔요 */
function Segments({ text, terms }: { text: string; terms: Record<string, string> }) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g)
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[\[([^\]]+)\]\]$/)
        if (!m) return <span key={i}>{part}</span>
        const word = m[1]!
        const tip = terms[word]
        if (!tip) return <span key={i}>{word}</span>
        return (
          <span key={i} tabIndex={0} className={s.term}>
            {word}
            <span role="tooltip" className={s.termTip}>
              {tip}
            </span>
          </span>
        )
      })}
    </>
  )
}

/** 목업의 인포그래픽 — 실제로는 Claude 가 SVG 를 만들어요 */
function InfoGraphic() {
  return (
    <div className={s.info}>
      <svg viewBox="0 0 480 200" role="img" aria-label="RNN에서 LSTM을 거쳐 Transformer로">
        <defs>
          <marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0 0l8 4-8 4z" fill="var(--text-dim)" />
          </marker>
        </defs>
        {[
          { x: 20, label: 'RNN', note: '순서대로 계산' },
          { x: 180, label: 'LSTM [13]', note: '게이트로 기억 조절' },
          { x: 340, label: 'Transformer', note: '어텐션만으로 병렬' },
        ].map((b, i) => (
          <g key={b.label}>
            <rect
              x={b.x}
              y={60}
              width={120}
              height={70}
              rx={10}
              fill="var(--bg)"
              stroke="var(--border)"
            />
            <text x={b.x + 60} y={90} textAnchor="middle" fontSize="14" fontWeight="700" fill="var(--text)">
              {b.label}
            </text>
            <text x={b.x + 60} y={110} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
              {b.note}
            </text>
            {i < 2 && (
              <line
                x1={b.x + 124}
                y1={95}
                x2={b.x + 174}
                y2={95}
                stroke="var(--text-dim)"
                strokeWidth="1.5"
                markerEnd="url(#ar)"
              />
            )}
          </g>
        ))}
      </svg>
    </div>
  )
}

function pillStyle(anchor: ChatAnchor | null): CSSProperties {
  if (!anchor) return { right: 20, bottom: 20 }
  return { left: anchor.x, top: anchor.y + 8 }
}

/* ── 아이콘 ───────────────────────────────────────────────── */

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

const SparkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16l-1.8-4.5L5 9.7l5.2-1.8z" />
  </svg>
)
const TrashIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </svg>
)
const MinusIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M5 12h14" />
  </svg>
)
const CloseIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)
const BubbleIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true" style={{ marginTop: 3 }}>
    <path d="M5 18l-1.5 3.5L8 20a8.5 8.5 0 10-3-2z" />
  </svg>
)
const ArrowUpIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} strokeWidth="2" aria-hidden="true">
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
)
