import { Fragment } from 'react'
import type { ReactNode } from 'react'

/**
 * Claude 답 글에 오는 `**굵게**`를 굵은 글씨로 그려요 (별표를 그대로 보이지 않게).
 * 나머지 마크다운은 건드리지 않아요 — 줄바꿈은 쓰는 쪽의 `white-space: pre-wrap`이 살려요.
 */
export function inlineBold(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g)
  return parts.map((part, i) => {
    const m = part.match(/^\*\*([^*\n]+)\*\*$/)
    return m ? <strong key={i}>{m[1]}</strong> : <Fragment key={i}>{part}</Fragment>
  })
}
