/**
 * 시각 표시. 목업의 두 가지 꼴을 따라요.
 * - 목록의 "최근 활동": `3분` · `어제` · `2일` · `지난주` · `2주` · `2달`
 * - 파일 표의 "수정": `12분 전` · `어제` · `11/20`
 */

const MIN = 60
const HOUR = 60 * MIN
const DAY = 24 * HOUR

/** epoch 초 → "3분" 꼴 (목록의 최근 활동) */
export function agoShort(epochSec: number | null | undefined, now = Date.now() / 1000): string {
  if (!epochSec) return ''
  const d = Math.max(0, now - epochSec)
  if (d < MIN) return '방금'
  if (d < HOUR) return `${Math.floor(d / MIN)}분`
  if (d < DAY) return `${Math.floor(d / HOUR)}시간`
  if (d < 2 * DAY) return '어제'
  if (d < 7 * DAY) return `${Math.floor(d / DAY)}일`
  if (d < 14 * DAY) return '지난주'
  if (d < 30 * DAY) return `${Math.floor(d / (7 * DAY))}주`
  if (d < 365 * DAY) return `${Math.max(1, Math.floor(d / (30 * DAY)))}개월`
  return `${Math.floor(d / (365 * DAY))}년`
}

/** epoch 초 → "12분 전" · "어제" · "11/20" (파일 표) */
export function whenShort(epochSec: number | null | undefined, now = Date.now() / 1000): string {
  if (!epochSec) return '—'
  const d = Math.max(0, now - epochSec)
  if (d < MIN) return '방금'
  if (d < HOUR) return `${Math.floor(d / MIN)}분 전`
  if (d < DAY) return `${Math.floor(d / HOUR)}시간 전`
  if (d < 2 * DAY) return '어제'
  const t = new Date(epochSec * 1000)
  const md = `${t.getMonth() + 1}/${t.getDate()}`
  return t.getFullYear() === new Date(now * 1000).getFullYear() ? md : `${t.getFullYear()}/${md}`
}

/** 바이트 → "3.2 GB" */
export function bytes(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v >= 10 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

/** 초 → "3시간 12분" */
export function duration(sec: number): string {
  if (sec < MIN) return `${Math.floor(sec)}초`
  if (sec < HOUR) return `${Math.floor(sec / MIN)}분`
  if (sec < DAY) return `${Math.floor(sec / HOUR)}시간 ${Math.floor((sec % HOUR) / MIN)}분`
  return `${Math.floor(sec / DAY)}일 ${Math.floor((sec % DAY) / HOUR)}시간`
}
