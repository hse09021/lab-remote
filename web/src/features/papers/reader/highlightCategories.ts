import type { HighlightCategory } from '@/api/types'

/** 하이라이트 5종. 색은 tokens.css의 --hl-* 가 갖고 있어요 */
export const HIGHLIGHT_CATEGORIES: Array<{ id: HighlightCategory; label: string }> = [
  { id: 'core', label: '핵심 혁신' },
  { id: 'method', label: '방법' },
  { id: 'result', label: '결과' },
  { id: 'check', label: '확인 필요' },
  { id: 'memo', label: '내 메모' },
]

/** 아웃라인 줄에 찍는 점은 메모를 빼고 네 가지예요 (목업과 같아요) */
export const OUTLINE_DOT_CATEGORIES: HighlightCategory[] = [
  'core',
  'method',
  'result',
  'check',
]

export type HighlightToggles = Record<HighlightCategory, boolean>

export const ALL_HIGHLIGHTS_ON: HighlightToggles = {
  core: true,
  method: true,
  result: true,
  check: true,
  memo: true,
}
