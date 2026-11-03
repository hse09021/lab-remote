import clsx from 'clsx'
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'
import s from './Button.module.css'

export type ButtonVariant =
  | 'primary'
  | 'accent'
  | 'outline'
  | 'ghost'
  | 'pill'
  | 'attention'
  | 'danger'
  | 'dangerOutline'

export type ButtonSize = 'sm' | 'md' | 'lg'

interface Common {
  variant?: ButtonVariant
  size?: ButtonSize
  /** 상자 크기는 그대로 두고 글자만 한 단계 작게 */
  compact?: boolean
  fullWidth?: boolean
  children?: ReactNode
  className?: string
}

type AsButton = Common &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & { href?: undefined }

type AsLink = Common &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'className'> & { href: string }

export type ButtonProps = AsButton | AsLink

/**
 * 목업의 버튼은 전부 인라인 스타일이었지만 변형은 8가지로 수렴해요.
 * `프로젝트 생성`이나 배너 CTA처럼 <a>로 렌더되는 것도 있어서
 * href를 주면 링크가 돼요.
 */
export function Button(props: ButtonProps) {
  const {
    variant = 'outline',
    size = 'lg',
    compact = false,
    fullWidth = false,
    className,
    children,
    ...rest
  } = props

  const cls = clsx(
    s.base,
    s[size],
    s[variant],
    compact && s.compact,
    fullWidth && s.full,
    className,
  )

  if ('href' in rest && rest.href !== undefined) {
    return (
      <a className={cls} {...(rest as AnchorHTMLAttributes<HTMLAnchorElement>)}>
        {children}
      </a>
    )
  }

  const { type = 'button', ...buttonRest } = rest as ButtonHTMLAttributes<HTMLButtonElement>
  return (
    <button type={type} className={cls} {...buttonRest}>
      {children}
    </button>
  )
}
