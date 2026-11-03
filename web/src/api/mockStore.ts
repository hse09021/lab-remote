import type { Paper, Permission, PermissionMode, ReadStatus } from './types'

/**
 * 목업 모드에서 "내가 바꾼 것"을 담아 두는 모듈 단위 저장소예요.
 *
 * mock JSON 은 처음 상태이고, 여기 담긴 값이 그 위에 덮여요.
 * 화면 상태(useState)로 들고 있으면 다른 화면에 갔다 오거나 쿼리 캐시가
 * 비워질 때 사라지니, 모든 변경은 이 저장소를 고치고 쿼리를 무효화해요.
 *
 * FastAPI 가 붙으면 이 파일은 안 쓰여요 (client.ts 가 실제 요청으로 넘어가요).
 */

export interface UserAnnotation {
  id: string
  paperId: string
  /** 내가 칠한 하이라이트 / 내가 쓴 주석. AI 하이라이트는 여기 안 들어와요 */
  kind: 'highlight' | 'note'
  /** 하이라이트면 고른 글, 주석이면 내가 쓴 메모 */
  text: string
  /** 주석이 어떤 글에 달렸는지 (하이라이트는 text 와 같아요) */
  source: string
  sectionId: string
  page: number
  /** HTML 보기에서 다시 그릴 자리 — 블록 id + 글자 오프셋 */
  anchor: { blockId: string; start: number; end: number } | null
  /** PDF 보기에서 다시 그릴 자리 — pt(612×792) 사각형 */
  boxes: Array<[number, number, number, number]> | null
  createdAt: number
}

export interface MockState {
  version: number
  /** 논문별 읽음 상태 */
  readStatus: Record<string, ReadStatus>
  /** 인용 카드로 보관한 논문 (papers 목록 앞에 붙어요) */
  savedPapers: Paper[]
  /** 논문별 내 하이라이트·주석 */
  annotations: Record<string, UserAnnotation[]>
  /** 논문별 요약 MD 수정본 */
  summaryMd: Record<string, string>
  /** 권한 설정 저장값 */
  permissions: { mode: PermissionMode; overrides: Record<string, Permission> } | null
  /** 수치 불일치에서 고른 재현 목표 */
  discrepancy: Record<string, string>
}

const VERSION = 1
const KEY = 'lab-remote.mock.v1'

const empty = (): MockState => ({
  version: VERSION,
  readStatus: {},
  savedPapers: [],
  annotations: {},
  summaryMd: {},
  permissions: null,
  discrepancy: {},
})

/* ── localStorage ─────────────────────────────────────────── */

function load(): MockState {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return empty()
    const parsed = JSON.parse(raw) as Partial<MockState>
    // 모양이 바뀌면 지난 값은 버려요
    if (parsed.version !== VERSION) return empty()
    return { ...empty(), ...parsed, version: VERSION }
  } catch {
    // 사생활 보호 모드·용량 초과 등 — 메모리만 써요
    return empty()
  }
}

function save(next: MockState) {
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // 못 써도 이번 세션에서는 메모리 값으로 돌아가요
  }
}

let state: MockState = load()

/** 바뀔 때마다 알려 줘요 (쿼리 무효화는 부른 쪽이 해요) */
export const readMockState = (): MockState => state

function update(fn: (prev: MockState) => MockState) {
  state = fn(state)
  save(state)
}

/** 처음 상태로 — 개발 모드에서 ?reset-mock 으로도 불려요 */
export function resetMockStore() {
  state = empty()
  try {
    localStorage.removeItem(KEY)
  } catch {
    // 지우지 못해도 메모리는 비웠어요
  }
}

/* ── 읽기: mock JSON 위에 내 값 덮기 ──────────────────────── */

export function overlayPapers(papers: Paper[]): Paper[] {
  const { savedPapers, readStatus } = state
  const withStatus = (p: Paper): Paper =>
    readStatus[p.id] ? { ...p, status: readStatus[p.id] } : p
  return [...savedPapers.map(withStatus), ...papers.map(withStatus)]
}

export function overlaySummaryMd(paperId: string, markdown: string): string {
  return state.summaryMd[paperId] ?? markdown
}

export const readAnnotations = (paperId: string): UserAnnotation[] =>
  state.annotations[paperId] ?? []

export const readPermissions = () => state.permissions

export const readDiscrepancy = (paperId: string) => state.discrepancy[paperId] ?? null

/* ── 쓰기 ─────────────────────────────────────────────────── */

export function setReadStatus(id: string, status: ReadStatus) {
  update((prev) => ({ ...prev, readStatus: { ...prev.readStatus, [id]: status } }))
}

export function addSavedPaper(paper: Paper) {
  update((prev) => ({
    ...prev,
    savedPapers: [paper, ...prev.savedPapers.filter((p) => p.id !== paper.id)],
  }))
}

export function removeSavedPaper(id: string) {
  update((prev) => ({
    ...prev,
    savedPapers: prev.savedPapers.filter((p) => p.id !== id),
    readStatus: Object.fromEntries(
      Object.entries(prev.readStatus).filter(([k]) => k !== id),
    ) as Record<string, ReadStatus>,
  }))
}

let seq = 0

export function addAnnotation(
  input: Omit<UserAnnotation, 'id' | 'createdAt'>,
): UserAnnotation {
  const made: UserAnnotation = {
    ...input,
    id: `u-${Date.now().toString(36)}-${++seq}`,
    createdAt: Date.now(),
  }
  update((prev) => ({
    ...prev,
    annotations: {
      ...prev.annotations,
      [input.paperId]: [made, ...(prev.annotations[input.paperId] ?? [])],
    },
  }))
  return made
}

/** 되돌리기 — 지웠던 것을 만든 시각 순서 그대로 다시 넣어요 */
export function restoreAnnotation(annotation: UserAnnotation) {
  update((prev) => {
    const list = [...(prev.annotations[annotation.paperId] ?? []), annotation].sort(
      (a, b) => b.createdAt - a.createdAt,
    )
    return { ...prev, annotations: { ...prev.annotations, [annotation.paperId]: list } }
  })
}

export function updateAnnotation(paperId: string, id: string, text: string) {
  update((prev) => ({
    ...prev,
    annotations: {
      ...prev.annotations,
      [paperId]: (prev.annotations[paperId] ?? []).map((a) =>
        a.id === id ? { ...a, text } : a,
      ),
    },
  }))
}

export function removeAnnotation(paperId: string, id: string) {
  update((prev) => ({
    ...prev,
    annotations: {
      ...prev.annotations,
      [paperId]: (prev.annotations[paperId] ?? []).filter((a) => a.id !== id),
    },
  }))
}

export function setSummaryMd(paperId: string, markdown: string | null) {
  update((prev) => {
    const next = { ...prev.summaryMd }
    if (markdown === null) delete next[paperId]
    else next[paperId] = markdown
    return { ...prev, summaryMd: next }
  })
}

export function setPermissions(value: MockState['permissions']) {
  update((prev) => ({ ...prev, permissions: value }))
}

export function setDiscrepancy(paperId: string, target: string) {
  update((prev) => ({ ...prev, discrepancy: { ...prev.discrepancy, [paperId]: target } }))
}
