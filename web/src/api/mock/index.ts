import { ApiError } from '../client'

/**
 * API 경로 → mock 모듈 매핑.
 * 화면을 하나씩 옮길 때마다 여기에 JSON을 등록해요.
 * 동적 import라 쓰지 않는 mock은 번들에 들어가지 않아요.
 */
const MOCKS: Record<string, () => Promise<{ default: unknown }>> = {
  '/projects': () => import('./projects.json'),
  '/experiments': () => import('./experiments.json'),
  '/experiments/dashboard': () => import('./dashboard.json'),
  '/experiments/events': () => import('./events.json'),
  '/experiments/permissions': () => import('./permissions.json'),
  '/code/files': () => import('./code-files.json'),
  '/code/tree': () => import('./file-tree.json'),
  '/code/terminal': () => import('./terminal.json'),
  '/code/commits': () => import('./commits.json'),
  '/code/chat': () => import('./code-chat.json'),
  '/code/run': () => import('./code-run.json'),
  '/papers': () => import('./papers.json'),
  '/papers/summaries': () => import('./paper-summaries.json'),
  '/papers/chat': () => import('./library-chat.json'),
}

export async function loadMock<T>(path: string): Promise<T> {
  const load = MOCKS[path]
  if (!load) {
    throw new ApiError(404, path, `등록된 mock이 없어요: ${path}`)
  }
  const mod = await load()
  return mod.default as T
}

export const hasMock = (path: string) => path in MOCKS
