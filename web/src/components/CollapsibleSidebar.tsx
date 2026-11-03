import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'
import s from './CollapsibleSidebar.module.css'

type Side = 'left' | 'right'

interface RailProps {
  side: Side
  label: string
  onExpand: () => void
}

/** 사이드바를 접었을 때 남는 48px 띠 */
export function CollapsedRail({ side, label, onExpand }: RailProps) {
  return (
    <div data-side={side} className={s.rail}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={false}
        title={label}
        onClick={onExpand}
        className={s.toggle}
      >
        <PanelIcon side={side} />
      </button>
    </div>
  )
}

interface Props {
  /** usePaneResize의 style. 접혀 있으면 display:none */
  style: CSSProperties
  /** <nav> 또는 <aside>의 접근성 이름 */
  label: string
  side?: Side
  onCollapse: () => void
  /** 접기 버튼 행을 직접 그릴 거면 false */
  showCollapseButton?: boolean
  /** 배경을 깔지 않아요 (리더 AI 패널은 흰 배경이에요) */
  bare?: boolean
  as?: 'nav' | 'aside'
  children: ReactNode
  className?: string
}

/**
 * 접고 펼치는 사이드바. 목업 4개 화면에 같은 모양으로 있어요.
 * 크기 조절은 usePaneResize + Resizer가 담당하고, 이 컴포넌트는 껍데기예요.
 */
export function CollapsibleSidebar({
  style,
  label,
  side = 'left',
  onCollapse,
  showCollapseButton = true,
  bare = false,
  as: Tag = 'nav',
  children,
  className,
}: Props) {
  return (
    <Tag
      aria-label={label}
      style={style}
      data-bare={bare}
      className={clsx(s.panel, className)}
    >
      {showCollapseButton && (
        <div className={s.header}>
          <button
            type="button"
            aria-label={`${label} 접기`}
            aria-expanded
            title="접기"
            onClick={onCollapse}
            className={s.toggle}
          >
            <PanelIcon side={side} />
          </button>
        </div>
      )}
      {children}
    </Tag>
  )
}

function PanelIcon({ side }: { side: Side }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d={side === 'left' ? 'M9 4v16' : 'M15 4v16'} />
    </svg>
  )
}
