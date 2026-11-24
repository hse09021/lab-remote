import type { PtRect } from '@/api/types'

/**
 * 선택한 텍스트가 본문 어디인지 — 나중에 그 자리에 다시 그리기 위한 값이에요.
 * HTML은 블록 id + 글자 오프셋, PDF는 pt(612×792) 사각형을 써요.
 */
export interface SelectionPlace {
  page: number
  anchor: { blockId: string; start: number; end: number } | null
  boxes: PtRect[] | null
}

/** 블록 안에서 시작 지점까지의 글자 수 (TreeWalker로 텍스트만 세요) */
function offsetWithin(block: HTMLElement, node: Node, nodeOffset: number): number | null {
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  let count = 0
  let current = walker.nextNode()
  while (current) {
    if (current === node) return count + nodeOffset
    count += current.textContent?.length ?? 0
    current = walker.nextNode()
  }
  return null
}

/**
 * 드래그 선택 → 블록 id + 오프셋.
 * id가 있는 가장 가까운 조상을 블록으로 봐요 (샘플·arXiv HTML 모두 id가 있어요).
 */
export function placeFromRange(range: Range): SelectionPlace['anchor'] {
  const start = range.startContainer
  const el = (start.nodeType === 1 ? (start as HTMLElement) : start.parentElement) ?? null
  const block = el?.closest<HTMLElement>('[id]')
  if (!block) return null

  const from = offsetWithin(block, range.startContainer, range.startOffset)
  const to = offsetWithin(block, range.endContainer, range.endOffset)
  if (from === null || to === null) return null

  return { blockId: block.id, start: Math.min(from, to), end: Math.max(from, to) }
}

/** 블록 id + 오프셋 → 다시 Range로 (본문에 그릴 때) */
export function rangeFromAnchor(
  root: HTMLElement,
  anchor: { blockId: string; start: number; end: number },
): Range | null {
  const block = root.querySelector<HTMLElement>(`#${CSS.escape(anchor.blockId)}`)
  if (!block) return null

  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  let count = 0
  let startNode: Node | null = null
  let startOffset = 0
  let endNode: Node | null = null
  let endOffset = 0

  let node = walker.nextNode()
  while (node) {
    const len = node.textContent?.length ?? 0
    if (!startNode && count + len >= anchor.start) {
      startNode = node
      startOffset = anchor.start - count
    }
    if (count + len >= anchor.end) {
      endNode = node
      endOffset = anchor.end - count
      break
    }
    count += len
    node = walker.nextNode()
  }

  if (!startNode || !endNode) return null
  const range = document.createRange()
  try {
    range.setStart(startNode, startOffset)
    range.setEnd(endNode, endOffset)
  } catch {
    // 본문이 바뀌어 오프셋이 안 맞으면 그리지 않아요
    return null
  }
  return range
}
