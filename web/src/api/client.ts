import { loadMock } from './mock'
import { applyMockWrite } from './mock/writes'
import { resetMockStore } from './mockStore'

/**
 * 어느 API를 서버에서 받나 (v3는 화면을 한 단계씩 실제 API로 옮겨요).
 *
 * - `VITE_USE_MOCK=true`(또는 안 줌) — **섞어 써요**: `LIVE_PREFIXES`는 서버, 나머지는 mock.
 *   v1의 `.env`(`true`)를 그대로 둬도 실제 API가 생긴 화면은 서버로 가요.
 * - `VITE_USE_MOCK=all` — 전부 mock (서버 없이 화면만 볼 때. 실제 API 화면은 비어요)
 * - `VITE_USE_MOCK=false` — 전부 서버
 */
const MOCK_MODE = import.meta.env.VITE_USE_MOCK
const BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** 서버 API가 생긴 경로. 단계마다 늘어나요 (PLAN 6장). */
const LIVE_PREFIXES = ['/health', '/projects', '/system', '/inbox', '/notify', '/dashboard', '/agents', '/approvals', '/events', '/schedules', '/conda'] as const

/** 바꾸는 요청에 붙이는 헤더 — 서버가 다른 사이트에서 온 요청을 거절하는 근거예요 */
const MUTATION_HEADER = { 'X-Lab-Remote': '1' }

/**
 * 일부만 서버로 가는 경로 — Papers는 vault로 만들어요. 미리 만든 리더 데이터(`/papers/{id}/reader`)와
 * 목업 대화(`/papers/chat`)만 mock이고, vault 논문의 리더는 PDF · arXiv HTML로 화면에서 만들어요.
 */
const LIVE_PATTERNS: Array<[RegExp, readonly string[]]> = [
  [/^\/papers$/, ['GET']],
  [/^\/papers\/(graph|vault|summary-md|summaries|notes)$/, ['GET', 'PUT']],
  // AI 요약 (누를 때만 · vault에 새 파일) · 요약 MD 수정 (요약 파일만)
  [/^\/papers\/[^/]+\/summary$/, ['GET', 'POST']],
  [/^\/papers\/[^/]+\/summary-md$/, ['PUT']],
  [/^\/papers\/[^/]+$/, ['PATCH']],
  // 논문 추가 (vault에 새 노트 · PDF) · PDF 내려받기
  [/^\/papers\/arxiv$/, ['POST']],
  // 휴지통 · 모음 · BibTeX · 참고문헌 보관 (lab.remote에만 기록)
  [/^\/papers\/collections$/, ['GET', 'POST']],
  [/^\/papers\/collections\/[^/]+$/, ['DELETE']],
  [/^\/papers\/collections\/[^/]+\/papers$/, ['POST']],
  [/^\/papers\/bibtex$/, ['GET']],
  [/^\/papers\/reference$/, ['POST']],
  [/^\/papers\/[^/]+\/trash$/, ['PUT']],
  // 내 하이라이트 · 주석 (데이터 폴더에 — 기기끼리 같이 봐요)
  [/^\/papers\/[^/]+\/annotations$/, ['GET', 'POST']],
  [/^\/papers\/[^/]+\/annotations\/[^/]+$/, ['PATCH', 'DELETE']],
  // 리더 AI (설명 · 질문 · 번역 · 분석)
  [/^\/papers\/[^/]+\/ai$/, ['POST']],
  [/^\/papers\/ai\/[^/]+$/, ['GET']],
  [/^\/papers\/[^/]+\/analysis$/, ['GET']],
  // 라이브러리에 묻기 (vault를 읽기 전용으로)
  [/^\/papers\/ask$/, ['POST']],
  [/^\/papers\/ask\/[^/]+$/, ['GET']],
  [/^\/papers\/[^/]+\/pdf$/, ['GET']],
  [/^\/papers\/[^/]+\/pdf\/fetch$/, ['POST']],
  // 재현 목표 고르기 (AI 분석이 찾은 수치 불일치)
  [/^\/papers\/[^/]+\/discrepancy$/, ['PUT']],
  // arXiv HTML 본문 · 받기 · 상태
  [/^\/papers\/[^/]+\/html$/, ['GET', 'POST']],
  [/^\/papers\/[^/]+\/html\/state$/, ['GET']],
]

const isLive = (path: string, method = 'GET') =>
  LIVE_PREFIXES.some((p) => path === p || path.startsWith(p + '/') || path.startsWith(p + '?')) ||
  LIVE_PATTERNS.some(([re, methods]) => re.test(path.split('?')[0]) && methods.includes(method))

function useMockFor(path: string, method = 'GET') {
  if (MOCK_MODE === 'all') return true
  if (MOCK_MODE === 'false') return false
  return !isLive(path, method)
}

/** 서버가 준 `{detail}`을 그대로 보여 줘요 (한국어 해요체로 와요) */
async function errorOf(res: Response, path: string) {
  let message: string | undefined
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') message = body.detail
  } catch {
    // 본문이 JSON이 아니면 상태 코드만
  }
  return new ApiError(res.status, path, message)
}

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
 * 준비되면 VITE_USE_MOCK=false로 바꾸는 것만으로 넘어가야 하니까요.
 */
export async function get<T>(path: string): Promise<T> {
  if (useMockFor(path)) {
    await sleep(MOCK_DELAY_MS)
    return loadMock<T>(path)
  }

  const res = await fetch(BASE + path, {
    headers: { Accept: 'application/json' },
  })

  if (!res.ok) throw await errorOf(res, path)
  return (await res.json()) as T
}

export async function send<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  if (useMockFor(path, method)) {
    await sleep(MOCK_DELAY_MS)
    // 목업 모드에서는 모듈 저장소를 고쳐요. 부른 쪽이 쿼리를 무효화해요.
    return applyMockWrite(method, path, body) as T
  }

  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...MUTATION_HEADER },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!res.ok) throw await errorOf(res, path)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 파일 내용을 그대로 올려요 (multipart를 쓰지 않아요). 서버 전용이에요. */
export async function upload<T>(path: string, file: Blob): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/octet-stream', ...MUTATION_HEADER },
    body: file,
  })
  if (!res.ok) throw await errorOf(res, path)
  return (await res.json()) as T
}

/** 내려받기·링크용 주소 */
export const apiUrl = (path: string) => BASE + path

export const isMockMode = () => MOCK_MODE === 'all'
export const isMockPath = (path: string, method = 'GET') => useMockFor(path, method)

/**
 * 개발 모드에서 ?reset-mock을 붙이면 목업 저장소를 처음 상태로 돌려요.
 * 주소에서 바로 빼서 새로 고침해도 다시 지워지지 않게 해요.
 */
export function resetMockFromUrl() {
  if (!import.meta.env.DEV || MOCK_MODE === 'false') return false
  const url = new URL(window.location.href)
  if (!url.searchParams.has('reset-mock')) return false
  resetMockStore()
  url.searchParams.delete('reset-mock')
  window.history.replaceState(null, '', url.toString())
  return true
}

export { resetMockStore }
export const apiBase = () => BASE
