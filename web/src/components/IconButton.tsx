import clsx from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import s from './IconButton.module.css'

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  /** 스크린 리더용 이름. 아이콘만 있으니 꼭 필요해요 */
  label: string
  size?: number
  variant?: 'ghost' | 'tint' | 'outline'
  children: ReactNode
  className?: string
}

export function IconButton({
  label,
  size = 32,
  variant = 'ghost',
  children,
  className,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      aria-label={label}
      title={rest.title ?? label}
      style={{ width: size, height: size, flex: `0 0 ${size}px` }}
      className={clsx(s.button, s[variant], className)}
      {...rest}
    >
      {children}
    </button>
  )
}
