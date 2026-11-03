import clsx from 'clsx'
import s from './RadioOption.module.css'

interface Props {
  name: string
  desc?: string
  selected: boolean
  onSelect: () => void
  /** card = 권한 단계, row = 설계 토론 선택지 */
  variant?: 'card' | 'row'
  disabled?: boolean
}

/**
 * 라디오처럼 동작하는 선택 버튼.
 * 목업은 <button aria-pressed>로 만들었는데, 하나만 고르는 묶음이라
 * role="radio" + aria-checked 가 맞아요. 묶음은 RadioOptionGroup 이 감싸요.
 */
export function RadioOption({
  name,
  desc,
  selected,
  onSelect,
  variant = 'card',
  disabled = false,
}: Props) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      className={clsx(s.option, s[variant])}
    >
      <span className={s.head}>
        <span aria-hidden="true" className={s.dot} />
        <span className={s.name}>{name}</span>
      </span>
      {desc && <span className={s.desc}>{desc}</span>}
    </button>
  )
}

export function RadioOptionGroup({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={className}>
      {children}
    </div>
  )
}
