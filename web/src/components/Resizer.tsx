import clsx from 'clsx'
import type { ResizerProps } from '@/lib/usePaneResize'
import s from './Resizer.module.css'

interface Props {
  /** usePaneResize가 준 props. 패널이 접혀 있으면 null이라 아무것도 안 그려요 */
  handle: ResizerProps | null
  /** "라이브러리 메뉴 너비 조절" 처럼 무엇을 조절하는지 */
  label: string
  className?: string
}

/**
 * 패널 경계선. 드래그로 크기 조절, 포커스 후 화살표로 16px씩.
 * 목업의 `.rs` 클래스를 그대로 옮긴 거예요.
 */
export function Resizer({ handle, label, className }: Props) {
  if (!handle) return null
  return <div {...handle} aria-label={label} className={clsx(s.resizer, className)} />
}
