import o from '../overlays/Overlays.module.css'

/**
 * 섹션 헤딩 옆 AI 설명 버튼.
 * PDF 보기의 것과 같은 모양·같은 핸들러 자리를 써요 (동작은 리더 4).
 */
export function Sparkle({
  label,
  onClick,
  onHover,
}: {
  label: string
  onClick: (el: HTMLElement) => void
  onHover?: (el: HTMLElement | null) => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={(e) => onClick(e.currentTarget)}
      onMouseEnter={(e) => onHover?.(e.currentTarget)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={(e) => onHover?.(e.currentTarget)}
      onBlur={() => onHover?.(null)}
      style={{ position: 'static', marginTop: 0 }}
      className={o.sparkle}
    >
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
      <span className={o.tip}>
        설명 <span className={o.kbd}>E</span>
      </span>
    </button>
  )
}
