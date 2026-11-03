/**
 * 도메인 타입의 단일 출처.
 * mock JSON과 FastAPI 응답이 똑같이 이 타입을 만족해야 해요.
 * 목업의 renderVals()가 만들던 스타일 문자열(statusStyle, badge 등)은
 * 데이터가 아니므로 여기 넣지 않고 컴포넌트가 계산해요.
 */

/* ── 공통 ───────────────────────────────────────────────────── */

export type MainTab = 'papers' | 'experiments' | 'code'

/** 승인/상태 표시의 색 계열 */
export type Tone = 'neutral' | 'success' | 'warn' | 'solid' | 'muted'

/** PDF 좌표. 612×792 pt(US Letter) 공간의 [x0, y0, x1, y1] */
export type PtRect = readonly [number, number, number, number]

/* ── 논문 ───────────────────────────────────────────────────── */

export type ReadStatus = 'todo' | 'reading' | 'done'
export type SummaryState = 'done' | 'running' | 'none'
export type PaperSource = 'arxiv-html' | 'pdf'

export interface Paper {
  id: string
  title: string
  authors: string
  venue: string
  field: string
  model: string
  status: ReadStatus
  source: PaperSource
  summaryState: SummaryState
  /** "방금", "오늘 08:40" 같은 상대 표기 */
  access: string
  /** vault 안 요약 MD 경로. 없으면 null */
  path: string | null
}

/** 요약 한 줄 + 원문 근거 위치 */
export interface SummaryLine {
  text: string
  /** HTML 논문은 "§3.2.1", PDF는 "p.4" 또는 미확인이면 "p.[쪽]" */
  ref: string
}

export interface PaperSummary {
  path: string
  /** 원문 파일명. Obsidian 위키링크를 만들 때 써요 */
  file: string
  /** arXiv HTML 기반이면 true (위키링크 앵커 형식이 달라져요) */
  html: boolean
  title: string
  meta: string
  lines: SummaryLine[]
  fields: Array<{ label: string; value: string }>
  method: string
  result: string
  limitation: string
}

export type HighlightCategory = 'core' | 'method' | 'result' | 'check' | 'memo'

/* ── 실험 ───────────────────────────────────────────────────── */

export type ExperimentState = 'queued' | 'running' | 'done' | 'failed' | 'stopped'

export interface Experiment {
  id: string
  /** 조작변인. "rank 32 · lr 2e-4" */
  knob: string
  /** "AI 제안" 같은 꼬리말 */
  knobNote: string | null
  state: ExperimentState
  /** 대기 순번 (queued일 때) */
  queuePosition: number | null
  /** 0–100, running일 때 */
  progress: number | null
  bestAcc: string | null
  branch: string | null
  commit: string | null
  /** analysis.md / Failures.md 링크 라벨. 없으면 null */
  report: string | null
  /** "epoch 34/50 · 약 1시간 12분" */
  detail: string | null
}

/* ── 권한 ───────────────────────────────────────────────────── */

export type PermissionMode = 'manual' | 'error' | 'full'
export type Permission = 'allow' | 'ask' | 'block'

export interface PermissionModeOption {
  id: PermissionMode
  name: string
  desc: string
}

export interface PermissionAction {
  key: string
  name: string
  desc: string
  /** 프리셋별 기본값 */
  defaults: Record<PermissionMode, Permission>
  /** 잠긴 항목은 Hooks가 항상 막아요 — UI는 표시만 해요 */
  locked: boolean
}

/* ── 코드 ───────────────────────────────────────────────────── */

export type FileLang = 'yaml' | 'python' | 'markdown'

export interface CodeFile {
  id: string
  path: string
  label: string
  lang: FileLang
  readOnly: boolean
  /** "experiments › EXP-007 › config.yaml" */
  crumb: string
  content: string
  /** AI가 수정한 파일이면 수정 전 내용. DiffEditor 입력 */
  original: string | null
}

export interface FileNode {
  name: string
  kind: 'file' | 'dir'
  /** 디렉터리의 기본 펼침 상태 */
  open?: boolean
  children?: FileNode[]
  /** git 상태 배지 */
  gitStatus?: 'M' | 'U'
  /** "잠김" / "읽기 전용" / "gitignore" */
  lock?: string
  /** 눌렀을 때 열 CodeFile.id */
  fileId?: string
}
