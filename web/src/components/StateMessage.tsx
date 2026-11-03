import clsx from 'clsx'
import type { ReactNode } from 'react'
import { ApiError } from '@/api/client'
import { Button } from './Button'
import s from './StateMessage.module.css'

/** 데이터를 불러오는 중에 자리를 잡아 주는 회색 블록 */
export function Skeleton({
  width = '100%',
  height = 16,
  className,
}: {
  width?: number | string
  height?: number | string
  className?: string
}) {
  return (
    <div
      aria-hidden="true"
      style={{ width, height }}
      className={clsx(s.skeleton, className)}
    />
  )
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" className={s.block}>
      <span className={s.text}>{label}</span>
    </div>
  )
}

export function ErrorState({
  title = '불러오지 못했어요',
  error,
  onRetry,
}: {
  title?: string
  error: unknown
  onRetry?: () => void
}) {
  const detail =
    error instanceof ApiError
      ? `${error.status} · ${error.path}`
      : error instanceof Error
        ? error.message
        : String(error)

  return (
    <div role="alert" className={s.block}>
      <span className={s.title}>{title}</span>
      <span className={s.text}>잠시 뒤에 다시 시도해 주세요.</span>
      <span className={s.detail}>{detail}</span>
      {onRetry && (
        <Button size="md" onClick={onRetry}>
          다시 불러오기
        </Button>
      )}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className={s.block}>
      <span className={s.text}>{children}</span>
    </div>
  )
}
