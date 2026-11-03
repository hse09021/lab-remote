import { ApiError } from '../client'

/**
 * API 경로 → mock 모듈 매핑.
 * 2단계에서 화면을 하나씩 옮길 때마다 여기에 JSON을 등록해요.
 * 동적 import라 쓰지 않는 mock은 번들에 들어가지 않아요.
 *
 * 경로에 파라미터가 있으면 ':id' 자리를 쓰고 fixture 하나를 돌려주거나,
 * 로더가 id로 골라 주면 돼요 (예: /papers/:id/reader).
 */
const MOCKS: Record<string, () => Promise<{ default: unknown }>> = {
  // 2단계에서 채워요. 예:
  // '/papers': () => import('./papers.json'),
  // '/papers/summaries': () => import('./paper-summaries.json'),
  // '/experiments': () => import('./experiments.json'),
  // '/experiments/dashboard': () => import('./dashboard.json'),
  // '/permissions': () => import('./permissions.json'),
  // '/code/files': () => import('./code-files.json'),
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
