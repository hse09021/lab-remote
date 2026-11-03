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

/* ── 실험 ───────────────────────────────────────────────────── */

export type ExperimentState = 'queued' | 'running' | 'done' | 'failed' | 'stopped'

export interface Experiment {
  id: string
  /** 조작변인. "rank 32 · lr 2e-4" */
  knob: string
  /** "AI 제안" 같은 꼬리말 */
  knobNote: string | null
  state: ExperimentState
  /** 실패 사유 등. "실패 · 발산"의 뒷부분 */
  stateNote: string | null
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

/* ── 프로젝트 사이드바 ──────────────────────────────────────── */

export interface Project {
  id: string
  name: string
  running: boolean
  stateLabel: string
}

export interface SidebarView {
  id: string
  label: string
  to: string
  icon: 'grid' | 'shield'
  /** 권한 설정의 승인 대기 건수 같은 꼬리 배지 */
  badge: string | null
}

export interface Integration {
  label: string
  ok: boolean
}

export interface ProjectsPayload {
  projects: Project[]
  views: SidebarView[]
  integrations: Integration[]
}

/* ── 대시보드 ───────────────────────────────────────────────── */

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

export interface ResourceMeter {
  label: string
  /** 0–100 */
  pct: number
  value: string
  tone: 'accent' | 'attention' | 'neutral'
}

/** 좌표가 아니라 loss 값으로 저장해요 — 그려 주는 쪽이 스케일을 계산해요 */
export interface LearningCurve {
  title: string
  /** 측정한 epoch 번호 */
  epochs: number[]
  train: number[]
  val: number[]
  /** x축 전체 범위 */
  totalEpochs: number
  /** 현재 epoch. 점선 세로줄 위치 */
  currentEpoch: number
  /** y축 최댓값 (loss) */
  yMax: number
  wandbHref: string
}

export interface ApprovalNotice {
  count: number
  text: string
  ctaLabel: string
  ctaHref: string
}

export interface Dashboard {
  project: string
  modeLabel: string
  loopLabel: string
  /** 승인 대기가 없으면 null */
  approval: ApprovalNotice | null
  metrics: MetricTileData[]
  learningCurve: LearningCurve
  resources: ResourceMeter[]
  queueCaption: string
  /** 루프가 멈춰 있는지 (모바일에서 정지하면 true) */
  loopPaused: boolean
  eventsCaption: string
}

/* ── 결정·이벤트 기록 ───────────────────────────────────────── */

export interface EventEntry {
  time: string
  kind: string
  tone: 'warn' | 'success' | 'neutral'
  text: string
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

export type FileLang = 'yaml' | 'python' | 'markdown' | 'plaintext'

export interface EditorBanner {
  tone: 'info' | 'warn'
  title: string
  text: string
  actions: string[]
}

export interface CodeFile {
  id: string
  /** 프로젝트 기준 경로. 확장자로 언어를 정해요 */
  path: string
  label: string
  readOnly: boolean
  /** "experiments › EXP-007 › config.yaml" */
  crumb: string
  content: string
  /** AI가 수정한 파일이면 수정 전 내용. DiffEditor 입력 */
  original: string | null
  banner: EditorBanner | null
  /** 바뀐 줄 옆에 붙일 꼬리말. "← AI 변경" */
  diffNote: string | null
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
  /** 루트 뒤에 붙는 꼬리말. "[GPU 서버]" */
  note?: string
  /** gitignore 대상처럼 흐리게 */
  muted?: boolean
}

/* ── 하단 패널 ─────────────────────────────────────────────── */

export interface TerminalLine {
  kind: 'log' | 'prompt'
  text: string
  /** prompt 줄만: 사용자와 경로를 따로 칠해요 */
  user?: string
  path?: string
}

export interface TerminalPayload {
  session: string
  problems: number
  lines: TerminalLine[]
}

/* ── 소스 제어 ─────────────────────────────────────────────── */

export interface Commit {
  msg: string
  /** AI가 만든 커밋이면 'AI' */
  author: string | null
  sha: string
  branch: string
}

export interface ChangedFile {
  path: string
  status: 'M' | 'U' | 'D'
}

export interface SourceControl {
  branch: string
  ahead: string
  commitPlaceholder: string
  changes: ChangedFile[]
}

/* ── 실험 실행 패널 ────────────────────────────────────────── */

export interface RunDraft {
  name: string
  base: string
  changed: string
  env: string
  autoCommit: boolean
  newBranch: boolean
  newBranchName: string
  hint: string
}

export interface QueueItem {
  id: string
  state: string
  progress: number | null
  detail: string | null
  stoppable: boolean
}

export interface RecentRun {
  id: string
  result: string
  failed: boolean
}

export interface RunPayload {
  caption: string
  draft: RunDraft
  queue: QueueItem[]
  recent: RecentRun[]
  sourceControl: SourceControl
}

/* ── Claude Code 채팅 ──────────────────────────────────────── */

export type ChatNode =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; text: string; sources?: string[] }
  | { kind: 'tool'; tool: string; path: string; added: number; removed: number; text: string }
  | { kind: 'approval'; title: string; text: string }

export interface CodeChatPayload {
  session: string
  messages: ChatNode[]
}

/* ── 권한 설정 화면 ─────────────────────────────────────────── */

export interface NotificationTagList {
  title: string
  caption: string
  tags: string[]
  /** 가려 둔 웹훅 주소. 실제 URL은 서버에만 둬요 */
  webhookMasked: string
  testLabel: string
}

export interface KeyValue {
  label: string
  value: string
  /** accent = 연결됨·켜짐 같은 정상 상태 */
  tone: 'accent' | 'muted'
}

export interface ClaudePushCard {
  title: string
  caption: string
  rows: KeyValue[]
}

export interface ApprovalLogEntry {
  time: string
  action: string
  request: string
  result: string
  /** 아직 처리되지 않은 건만 알약으로 보여 줘요 */
  resultPending: boolean
  handledBy: string
  /**
   * 한 호출을 묶는 키. 한 호출이 "대기 중" → "허용"(또는 "거부 또는 미응답")
   * 으로 두 줄 이상 남아요. 화면은 같은 toolUseId 의 **마지막 줄**을 보여 주면
   * 돼요. 훅이 모르는 옛 기록은 빈 문자열이에요.
   */
  toolUseId: string
}

export interface PermissionsPayload {
  modes: PermissionModeOption[]
  actions: PermissionAction[]
  /** allow / ask / block 의 화면 글자 */
  labels: Record<Permission, string>
  actionsCaption: string
  /** 종료 조건은 '연구 전체 자동화'에서만 써요 */
  configPath: string
  stopLockNotice: string
  stopLockButton: string
  stopConditions: MetricTileData[]
  /** 다른 단계일 때 보여 줄 안내 */
  stopDisabledNotice: string
  discord: NotificationTagList
  claudePush: ClaudePushCard
  logPath: string
  approvalLog: ApprovalLogEntry[]
  /** 저장해 둔 권한 설정. 저장한 적 없으면 null */
  saved: { mode: PermissionMode; overrides: Record<string, Permission> } | null
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
  /** [[용어]] 에 붙는 뜻풀이 */
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

/* ── 실험 설계 초안 (FocusDesign) ───────────────────────────── */

/** 값 하나의 출처 */
export type DesignValueKind =
  /** 논문에서 그대로 확인한 값 */
  | 'confirmed'
  /** 리더의 수치 불일치에서 고른 값을 가져와요 */
  | 'fromReader'
  /** 논문에 없어서 내가 정해야 하는 값 */
  | 'estimate'

export interface DesignValue {
  key: string
  item: string
  /** confirmed 만 처음부터 값이 있어요 */
  value: string | null
  /** 근거 — 리더의 해당 섹션으로 이동해요 */
  evidence: { sectionId: string; label: string } | null
  kind: DesignValueKind
  /** 입력칸 안내 */
  hint: string | null
}

export interface DesignChoiceBlock {
  kind: 'choices'
  title: string
  /** startOptions / envOptions 중 어느 목록인지 */
  options: 'startOptions' | 'envOptions'
}

export type DesignChatBlock =
  | { kind: 'assistant'; text: string }
  | { kind: 'user'; text: string }
  | DesignChoiceBlock

export interface DesignOption {
  id: string
  label: string
  desc: string
}

export interface DesignDraft {
  paperId: string
  paperTitle: string
  spec: Array<{ label: string; value: string }>
  files: string[]
  filesNote: string
  values: DesignValue[]
  startOptions: DesignOption[]
  envOptions: DesignOption[]
  envLabels: Record<string, string>
  chat: DesignChatBlock[]
  /** 설계 토론 패널의 첨부 칩 */
  attachment: string
  /** 내가 넣어 둔 값. 없으면 null */
  saved: Record<string, string> | null
}

export type DesignDraftMap = Record<string, DesignDraft>
