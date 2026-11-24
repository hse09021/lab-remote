/**
 * PDF 글자 조각 안의 글자 위치를 폭 비율로 구해요.
 *
 * pdf.js 글자 층은 조각(대개 한 줄) 단위라, 구절이 줄 중간에서 시작하면 그 앞 글자들이
 * 차지하는 폭을 알아야 해요. "조각 폭 ÷ 글자 수"로 어림하면 W · m 같은 넓은 글자와
 * i · l 같은 좁은 글자가 섞여 한두 글자씩 어긋나요. 그래서 같은 글꼴 계열로 앞부분과
 * 전체를 재서 그 비율을 써요 — pdf.js가 글자 층의 가로 배율을 맞출 때와 같은 방식이에요.
 * 언어를 비워 둔(lang="") 캔버스로 재요 (pdf.js 측정 캔버스와 같은 글꼴이 고르게).
 */
let ctx: CanvasRenderingContext2D | null = null

function context(): CanvasRenderingContext2D | null {
  if (ctx) return ctx
  if (typeof document === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.lang = ''
  ctx = canvas.getContext('2d')
  return ctx
}

/** `str[0..index)`가 조각 폭에서 차지하는 비율 (0~1). 잴 수 없으면 글자 수 비율 */
export function prefixRatio(str: string, index: number, fontFamily = 'sans-serif'): number {
  const n = str.length
  if (n === 0) return 0
  const i = Math.max(0, Math.min(index, n))
  const c = context()
  if (!c) return i / n
  c.font = `100px ${fontFamily || 'sans-serif'}`
  const full = c.measureText(str).width
  if (!(full > 0)) return i / n
  return c.measureText(str.slice(0, i)).width / full
}
