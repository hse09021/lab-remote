import { ApiError } from '../client'
import { readAnnotations, readMockState } from '../mockStore'
import { applyOverlay } from './overlay'

/**
 * API 경로 → mock 모듈 매핑.
 * 화면을 하나씩 옮길 때마다 여기에 JSON을 등록해요.
 * 동적 import라 쓰지 않는 mock은 번들에 들어가지 않아요.
 */
const MOCKS: Record<string, () => Promise<{ default: unknown }>> = {
  '/code/files': () => import('./code-files.json'),
  '/code/tree': () => import('./file-tree.json'),
  '/code/terminal': () => import('./terminal.json'),
  '/code/commits': () => import('./commits.json'),
  '/code/chat': () => import('./code-chat.json'),
  '/code/run': () => import('./code-run.json'),
  '/papers': () => import('./papers.json'),
  '/papers/summaries': () => import('./paper-summaries.json'),
  '/papers/chat': () => import('./library-chat.json'),
  '/papers/attn/reader': () => import('./paper-attn.json'),
}

/**
 * JSON 파일 없이 저장소만 읽는 경로.
 * 내가 만든 것들이라 처음 상태가 "비어 있음"이에요.
 */
function loadFromStore<T>(path: string): T | undefined {
  const anns = path.match(/^\/papers\/([^/]+)\/annotations$/)
  if (anns) return readAnnotations(anns[1]) as T

  if (path === '/papers/summary-md') return readMockState().summaryMd as T

  return undefined
}

export async function loadMock<T>(path: string): Promise<T> {
  const stored = loadFromStore<T>(path)
  if (stored !== undefined) return stored

  const load = MOCKS[path]
  if (!load) {
    throw new ApiError(404, path, `등록된 mock이 없어요: ${path}`)
  }
  const mod = await load()
  // mock JSON 은 처음 상태 — 그 위에 내가 바꾼 값을 덮어요
  return applyOverlay(path, structuredClone(mod.default) as T)
}

export const hasMock = (path: string) =>
  path in MOCKS || loadFromStore(path) !== undefined
