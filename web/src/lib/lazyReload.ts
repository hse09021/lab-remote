import { lazy } from 'react'
import type { ComponentType } from 'react'

const KEY = 'labremote:chunk-reload'

/** 새로 빌드돼서 옛 조각 파일이 없어졌을 때 나는 오류인가 */
export function isChunkError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? '')
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported|ChunkLoadError|Loading chunk/i.test(msg)
}

/**
 * 새로 고침을 **한 번만** 해요 (새 index.html → 새 조각 이름).
 * 30초 안에 또 실패하면 다시 하지 않아요 — 계속 돌지 않게.
 */
export function reloadOnce(): boolean {
  try {
    const last = Number(sessionStorage.getItem(KEY) || 0)
    if (Date.now() - last < 30_000) return false
    sessionStorage.setItem(KEY, String(Date.now()))
  } catch {
    // 저장소를 못 쓰면 그냥 한 번 해요
  }
  window.location.reload()
  return true
}

/** `lazy`와 같지만, 옛 빌드라 조각을 못 받으면 페이지를 한 번 새로 고쳐요 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- React.lazy와 같은 제약
export function lazyReload<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) {
  return lazy(() =>
    load().catch((err: unknown) => {
      if (isChunkError(err) && reloadOnce()) return new Promise<{ default: T }>(() => {})
      throw err
    }),
  )
}
