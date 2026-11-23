import type { ReactNode } from 'react'

/**
 * 목업에 15곳 있던 sr-only 라벨.
 * 스타일은 styles/reset.css의 .sr-only에 있어요.
 */
export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>
}
