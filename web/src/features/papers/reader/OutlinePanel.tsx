import type { CSSProperties } from 'react'
import type { Highlight, PaperSection } from '@/api/types'
import { IconButton, ProgressBar } from '@/components'
import {
  HIGHLIGHT_CATEGORIES,
  OUTLINE_DOT_CATEGORIES,
  type HighlightToggles,
} from './highlightCategories'
import s from './OutlinePanel.module.css'

interface Props {
  style: CSSProperties
  onCollapse: () => void
  sections: PaperSection[]
  highlights: Highlight[]
  /** 지금 읽고 있는 섹션 */
  activeId: string | null
  onJump: (sectionId: string) => void
  /** 0–100 */
  progress: number
  /** PDF 보기일 때만 쪽 번호를 보여 줘요 */
  showPages: boolean
  toggles: HighlightToggles
  onToggle: (category: keyof HighlightToggles) => void
}

export function OutlinePanel({
  style,
  onCollapse,
  sections,
  highlights,
  activeId,
  onJump,
  progress,
  showPages,
  toggles,
  onToggle,
}: Props) {
  // 섹션마다 어떤 하이라이트가 있는지 (켜 둔 종류만 점을 찍어요)
  const dotsBySection = new Map<string, Set<string>>()
  for (const h of highlights) {
    if (!dotsBySection.has(h.section)) dotsBySection.set(h.section, new Set())
    dotsBySection.get(h.section)!.add(h.category)
  }

  const counts = HIGHLIGHT_CATEGORIES.map((c) => ({
    ...c,
    count: highlights.filter((h) => h.category === c.id).length,
  }))

  return (
    <aside aria-label="AI 아웃라인" style={style} className={s.panel}>
      <div className={s.head}>
        <span className={s.headTitle}>AI 아웃라인</span>
        <IconButton label="아웃라인 접기" aria-expanded onClick={onCollapse}>
          <PanelIcon />
        </IconButton>
      </div>

      <nav aria-label="논문 목차" className={s.list}>
        {sections.map((sec) => {
          const cats = dotsBySection.get(sec.id)
          return (
            <button
              key={sec.id}
              type="button"
              data-level={sec.level}
              aria-current={sec.id === activeId ? 'location' : undefined}
              onClick={() => onJump(sec.id)}
              style={{ '--indent': `${12 + sec.level * 14}px` } as CSSProperties}
              className={s.item}
            >
              <span className={s.num}>{sec.n}</span>
              <span className={s.title}>{sec.title}</span>
              <span aria-hidden="true" className={s.dots}>
                {OUTLINE_DOT_CATEGORIES.map((c) =>
                  cats?.has(c) && toggles[c] ? (
                    <span key={c} data-cat={c} className={s.dot} />
                  ) : null,
                )}
              </span>
              {showPages && <span className={s.page}>p.{sec.page}</span>}
            </button>
          )
        })}
      </nav>

      <div className={s.footer}>
        <div className={s.progressBlock}>
          <div className={s.progressRow}>
            <span>읽은 위치</span>
            <span className={s.mono}>{progress}%</span>
          </div>
          <ProgressBar value={progress} height={4} darkTrack label="읽은 위치" />
        </div>

        <span className={s.legendCaption}>하이라이트 · 눌러서 켜고 끄기</span>
        <div className={s.legend}>
          {counts.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={toggles[c.id]}
              onClick={() => onToggle(c.id)}
              className={s.chip}
            >
              <span aria-hidden="true" data-cat={c.id} className={s.swatch} />
              {c.label}
              <span className={s.count}>{c.count}</span>
            </button>
          ))}
        </div>
      </div>
    </aside>
  )
}

function PanelIcon() {
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
      <path d="M9 4v16" />
    </svg>
  )
}
