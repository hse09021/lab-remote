import { loadMock } from './mock'
import { applyMockWrite } from './mock/writes'
import { resetMockStore } from './mockStore'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message?: string,
  ) {
    super(message ?? `${status} ${path}`)
    this.name = 'ApiError'
  }
}

/** mock일 때 로딩 상태를 눈으로 확인할 수 있게 주는 지연 */
const MOCK_DELAY_MS = 150

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * 화면은 이 함수(와 features별 query 헬퍼)만 써요.
 * mock JSON을 화면에서 직접 import하지 않는 게 규칙이에요 — FastAPI가
 * 준비되면 VITE_USE_MOCK=false 로 바꾸는 것만으로 넘어가야 하니까요.
 */
export async function get<T>(path: string): Promise<T> {
  if (USE_MOCK) {
    await sleep(MOCK_DELAY_MS)
    return loadMock<T>(path)
  }

  const res = await fetch(BASE + path, {
    headers: { Accept: 'application/json' },
  })

  // TODO(인증): 401이면 로그인으로 보내요. spec IV의 인증 레이어가 붙으면 채워요.
  if (!res.ok) throw new ApiError(res.status, path)
  return (await res.json()) as T
}

export async function send<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  if (USE_MOCK) {
    await sleep(MOCK_DELAY_MS)
    // 목업 모드에서는 모듈 저장소를 고쳐요. 부른 쪽이 쿼리를 무효화해요.
    return applyMockWrite(method, path, body) as T
  }

  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!res.ok) throw new ApiError(res.status, path)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const isMockMode = () => USE_MOCK

/**
 * 개발 모드에서 ?reset-mock 을 붙이면 목업 저장소를 처음 상태로 돌려요.
 * 주소에서 바로 빼서 새로 고침해도 다시 지워지지 않게 해요.
 */
export function resetMockFromUrl() {
  if (!import.meta.env.DEV || !USE_MOCK) return false
  const url = new URL(window.location.href)
  if (!url.searchParams.has('reset-mock')) return false
  resetMockStore()
  url.searchParams.delete('reset-mock')
  window.history.replaceState(null, '', url.toString())
  return true
}

export { resetMockStore }
export const apiBase = () => BASE
