/**
 * 도메인 타입의 단일 출처.
 * mock JSON과 FastAPI 응답이 똑같이 이 타입을 만족해야 해요.
 * 목업의 renderVals()가 만들던 스타일 문자열(statusStyle, badge 등)은
 * 데이터가 아니므로 여기 넣지 않고 컴포넌트가 계산해요.
 */

/* ── 공통 ───────────────────────────────────────────────────── */

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
  /** Research Field 태그. 아직 분류 전이면 null */
  field: string | null
  /** 모델 태그. 아직 확인 전이면 null */
  model: string | null
  status: ReadStatus
  source: PaperSource
  summaryState: SummaryState
  /** "방금", "오늘 08:40" 같은 상대 표기 */
  access: string
  /** vault 안 요약 MD 경로. 없으면 null */
  path: string | null
  /** vault에 PDF 가 있나 (실제 API) */
  hasPdf?: boolean
  /** arXiv 번호 (실제 API) */
  arxiv?: string
  /** 들어 있는 모음 이름 (실제 API) */
  collections?: string[]
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
  authors: string
  venue: string
  title: string
  meta: string
  lines: SummaryLine[]
  fields: Array<{ label: string; value: string }>
  method: string
  result: string
  limitation: string
}

/** 요약이 있는 논문만 담겨요 */
export type PaperSummaryMap = Record<string, PaperSummary>

/* ── vault · 지식그래프 ─────────────────────────────────────── */

export interface VaultInfo {
  /** vault 폴더 절대 경로 */
  path: string
  /** 사람이 정한 위치인가 (아니면 데이터 폴더의 vault/) */
  custom: boolean
  exists: boolean
  papers: number
  notes: number
}

export type GraphNodeKind = 'paper' | 'project' | 'note'
export type GraphEdgeKind = 'cite' | 'use' | 'note'

export interface GraphNode {
  /** 논문은 노트 파일 이름, 프로젝트는 `project:<이름>`, 메모는 `note:<vault 안 경로>` */
  id: string
  kind: GraphNodeKind
  name: string
  /** 논문 분류(앞쪽 메타의 category). 프로젝트 · 메모는 고정 이름 */
  category: string
  meta: string
  path: string
}

export interface GraphEdge {
  from: string
  to: string
  kind: GraphEdgeKind
}

export interface PaperGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  vault: string
}

/* ── 라이브러리에 묻기 ──────────────────────────────────────── */

export interface ChatSource {
  label: string
  paperId: string
}

export interface LibraryChatMessage {
  role: 'user' | 'assistant'
  text: string
  sources: ChatSource[]
}

export interface LibraryChat {
  title: string
  caption: string
  messages: LibraryChatMessage[]
}

export type HighlightCategory = 'core' | 'method' | 'result' | 'check' | 'memo'

/* ── 숫자 칸 (Dashboard 2단계에서 다시 씀) ───────────────────────────────────────────────── */

export interface MetricTileData {
  label: string
  value: string
  /** 값 뒤에 작게 붙는 글자. "34" + " / 50" */
  valueSuffix?: string | null
  valueTone?: 'default' | 'accent'
  /** numeric = mono 큰 숫자, text = 본문 글꼴 문장 ("대기 후 재개") */
  valueVariant?: 'numeric' | 'text'
  sub: string
  subTone?: 'muted' | 'accent'
  /** 0–100. 있으면 값 아래 진행바가 생겨요 */
  progress?: number | null
}

export interface KeyValue {
  label: string
  value: string
  /** accent = 연결됨·켜짐 같은 정상 상태 */
  tone: 'accent' | 'muted'
}

/* ── 논문 리더 ──────────────────────────────────────────────── */

export interface PaperSection {
  id: string
  /** 섹션 번호. Abstract·References는 빈 문자열 */
  n: string
  title: string
  /** 0 = 대제목, 1·2 = 하위 */
  level: 0 | 1 | 2
  page: number
  /** PDF 좌표(612×792 pt) — 제목 기준선 y */
  y: number
  /** 제목 글자가 끝나는 x. 설명 버튼을 놓을 자리 */
  xEnd: number
  /** arXiv/LaTeXML 식 앵커. "S3.SS2.SSS1" */
  htmlAnchor: string | null
}

export interface Highlight {
  id: string
  category: HighlightCategory
  /** 어느 섹션에 속하는지 */
  section: string
  page: number
  /** PDF 좌표 사각형. 한 하이라이트가 여러 줄에 걸칠 수 있어요 */
  boxes: PtRect[]
  note: string
  /**
   * 샘플 골격에서 칠할 블록 id. 실제 arXiv HTML 이면 글자 단위로
   * 바꿀 수 있지만 지금은 블록 단위만 써요.
   */
  htmlBlock: string | null
}

export interface Reference {
  n: number
  authors: string
  short: string
  title: string
  venue: string
  arxiv: string | null
  year: number
  /** 본문에서 인용된 횟수 */
  citedCount: number
  inLibrary: boolean
  /** 왜 인용했는지 */
  why: string
}

/** 그림·수식처럼 "풀어서 설명받기"를 붙이는 영역 */
export interface ExplainZone {
  key: string
  kind: 'fig' | 'eq'
  page: number
  box: PtRect
  /** 액션 바를 영역 아래에 둘지 가운데 둘지 */
  barPlacement: 'bottom' | 'mid'
  /** 수식이면 복사할 LaTeX */
  latex: string | null
}

/** 본문에 찍힌 인용 번호 자리 */
export interface CiteSpot {
  n: number
  page: number
  box: PtRect
}

/** AI가 본문에서 뽑은 학습 설정 */
export interface ExtractedConfig {
  title: string
  caption: string
  rows: Array<{ label: string; value: string; sectionId: string; ref: string }>
}

/** 본문과 표의 수치가 어긋날 때 */
export interface DiscrepancyNote {
  title: string
  text: string
  options: Array<{ value: string; label: string }>
  /** 내가 고른 재현 목표. 아직 안 골랐으면 null */
  chosen: string | null
}

export interface InlineMemo {
  title: string
  meta: string
  text: string
}

export interface PaperReaderPayload {
  paperId: string
  title: string
  meta: string
  arxivId: string
  arxivUrl: string
  /** arXiv HTML이 없으면 PDF만 보여 줘요 */
  hasHtml: boolean
  pageCount: number
  /** 쪽 이미지 경로 앞부분. 개발용 fixtures */
  pageImageBase: string
  pageSize: { width: number; height: number }
  sections: PaperSection[]
  highlights: Highlight[]
  references: Reference[]
  /** 실제 참고문헌 수 (모델링한 것보다 많아요) */
  referenceTotal: number
  citationsCaption: string
  /** 원문 PDF 주소 (개발 서버의 fixtures) */
  pdfUrl: string
  /** 100% 일 때 쪽 너비(px) */
  baseWidth: number
  zoomLevels: number[]
  explainZones: ExplainZone[]
  citeSpots: CiteSpot[]
  extractedConfig: ExtractedConfig
  discrepancy: DiscrepancyNote
  inlineMemo: InlineMemo
  /** 섹션·그림·수식별 미리 써 둔 설명 */
  topics: Record<string, Topic>
  /** [[용어]]에 붙는 뜻풀이 */
  terms: Record<string, string>
  selectionSpot: SelectionSpot
}

/* ── 떠 있는 대화창 (리더 4) ────────────────────────────────── */

/** 설명 본문을 이루는 조각들 */
export type TopicBlock =
  | { p: string }
  | { li: string; p: string }
  | { h: string }
  | { rel: string; note: string }
  | { src: string; go: string }
  | { info: true }

export interface TopicQuestion {
  q: string
  a: string
  /** 답의 근거 섹션 */
  go: string
  src: string
}

export interface Topic {
  title: string
  /** 설명을 요청한 원문 한 줄 */
  quote?: string
  blocks: TopicBlock[]
  qs: TopicQuestion[]
}

/** 본문에서 선택했다고 가정하는 자리 (PDF 는 텍스트 레이어가 없어서) */
export interface SelectionSpot {
  page: number
  box: PtRect
  text: string
  /** 이 구절의 번역 (목업에 미리 써 둔 것) */
  translation: string
  translationNote: string
}

/** 대화창에 쌓이는 줄 */
export type ChatEntry =
  | { kind: 'user'; text: string }
  | { kind: 'loading' }
  | { kind: 'answer'; text: string; go?: string; src?: string }

