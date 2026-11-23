import clsx from 'clsx'
import type { ReactNode } from 'react'
import s from './SegmentedControl.module.css'

export interface SegmentedItem<T extends string> {
  value: T
  label: ReactNode
  /** 아이콘만 쓸 때 스크린 리더용 이름 */
  ariaLabel?: string
  /** 선택지별 색이 다를 때 */
  tone?: 'allow' | 'ask' | 'block'
}

interface Props<T extends string> {
  items: SegmentedItem<T>[]
  value: T
  onChange: (value: T) => void
  /** 그룹 이름. role=tablist일 때도 써요 */
  label: string
  size?: 'sm' | 'md'
  variant?: 'text' | 'icon'
  /** 가로로 꽉 채워요 (리더 AI 패널 탭) */
  fill?: boolean
  /** 탭으로 쓸 때. aria-selected + role=tab이 돼요 */
  asTabs?: boolean
  disabled?: boolean
  className?: string
}

/**
 * 목업 8곳에 나오는 세그먼트 컨트롤.
 * 라이브러리 보기 방식, 요약 보기(정리된/MD 원문), 리더 원문 형식(HTML/PDF),
 * 리더 AI 패널 탭, 권한 3단 선택, 모바일 읽음 상태가 모두 이 모양이에요.
 */
export function SegmentedControl<T extends string>({
  items,
  value,
  onChange,
  label,
  size = 'md',
  variant = 'text',
  fill = false,
  asTabs = false,
  disabled = false,
  className,
}: Props<T>) {
  return (
    <div
      role={asTabs ? 'tablist' : 'group'}
      aria-label={label}
      className={clsx(s.track, fill && s.fill, className)}
    >
      {items.map((item) => {
        const selected = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            role={asTabs ? 'tab' : undefined}
            aria-selected={asTabs ? selected : undefined}
            aria-pressed={asTabs ? undefined : selected}
            aria-label={item.ariaLabel}
            data-tone={item.tone}
            disabled={disabled}
            onClick={() => onChange(item.value)}
            className={clsx(s.segment, s[size], variant === 'icon' && s.icon)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
