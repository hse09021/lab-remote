/**
 * 선 아이콘 — docs/v3/mockups/IDE.dc.html · ADE.dc.html의 SVG를 그대로 옮겼어요.
 * 색은 `currentColor` 라 쓰는 쪽 글자색을 따라가요.
 */
import type { ReactNode } from 'react'

interface P {
  size?: number
  /** 선 굵기 — 목업은 작업 표시줄 1.7 · 작은 버튼 1.8 */
  weight?: number
}

function Svg({ size = 22, weight = 1.7, children }: P & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={weight}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

/** 탐색기 — 겹친 문서 */
export const FilesIcon = (p: P) => (
  <Svg {...p}>
    <path d="M14 3H8a2 2 0 00-2 2v12a2 2 0 002 2h9a2 2 0 002-2V8l-5-5z" />
    <path d="M14 3v5h5" />
    <path d="M3 8v11a2 2 0 002 2h9" />
  </Svg>
)

export const SearchIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Svg>
)

/** 소스 제어 — 갈래 */
export const GitIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="6" cy="5" r="2.2" />
    <circle cx="6" cy="19" r="2.2" />
    <circle cx="18" cy="8" r="2.2" />
    <path d="M6 7.2v9.6M18 10.2c0 4-6 3.5-11 7" />
  </Svg>
)

/** Scenario — 이어진 상자 */
export const ScenarioIcon = (p: P) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7" height="5" rx="1" />
    <rect x="14" y="10" width="7" height="5" rx="1" />
    <rect x="3" y="16" width="7" height="5" rx="1" />
    <path d="M10 5.5h2a2 2 0 012 2V10M14 12.5h-2a2 2 0 00-2 2V16" />
  </Svg>
)

/** 실행 — 플라스크 */
export const RunIcon = (p: P) => (
  <Svg {...p}>
    <path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 006 21h12a1.7 1.7 0 001.5-2.5L14 9V3" />
    <path d="M7 15h10" />
  </Svg>
)

/** 세션 — 말풍선 */
export const ChatIcon = (p: P) => (
  <Svg {...p}>
    <path d="M20 15a2 2 0 01-2 2H8l-4 4V5a2 2 0 012-2h12a2 2 0 012 2z" />
    <path d="M8 8h8M8 12h5" />
  </Svg>
)

export const GearIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
  </Svg>
)

export const PlusIcon = (p: P) => (
  <Svg size={17} weight={1.8} {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

/** 세션 기록 — 시계 */
export const HistoryIcon = (p: P) => (
  <Svg size={18} weight={1.8} {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </Svg>
)

/** 새 세션 — 동그라미 더하기 */
export const NewSessionIcon = (p: P) => (
  <Svg size={18} weight={1.8} {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 8v8M8 12h8" />
  </Svg>
)

export const NewFileIcon = (p: P) => (
  <Svg size={17} {...p}>
    <path d="M13 3H7a2 2 0 00-2 2v14a2 2 0 002 2h4" />
    <path d="M13 3v5h5v3" />
    <circle cx="17" cy="17" r="4" />
    <path d="M17 15v4M15 17h4" />
  </Svg>
)

export const NewFolderIcon = (p: P) => (
  <Svg size={17} {...p}>
    <path d="M11 19H5a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h6a2 2 0 012 2v2" />
    <circle cx="17" cy="17" r="4" />
    <path d="M17 15v4M15 17h4" />
  </Svg>
)

export const RefreshIcon = (p: P) => (
  <Svg size={17} {...p}>
    <path d="M20 12a8 8 0 11-2.3-5.7" />
    <path d="M20 4v4h-4" />
  </Svg>
)

export const CollapseAllIcon = (p: P) => (
  <Svg size={17} {...p}>
    <rect x="4" y="4" width="16" height="16" rx="3" />
    <path d="M8.5 12h7" />
  </Svg>
)

/** 닫기 — 엑스 */
export const CloseIcon = (p: P) => (
  <Svg size={18} weight={1.8} {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)

/* ── 이모지 · 기호 대신 쓰는 선 아이콘 (Mode · 입력창 · 체크 · 경고) ── */

/** Manual — 손바닥 */
export const HandIcon = (p: P) => (
  <Svg size={16} weight={1.8} {...p}>
    <path d="M18 11V6a2 2 0 00-4 0" />
    <path d="M14 10V4a2 2 0 00-4 0v2" />
    <path d="M10 10.5V6a2 2 0 00-4 0v8" />
    <path d="M18 8a2 2 0 114 0v6a8 8 0 01-8 8h-2c-2.8 0-4.5-.9-6-2.3l-3.6-3.6a2 2 0 012.8-2.8L7 15" />
  </Svg>
)

/** Edit automatically — 코드 꺾쇠 */
export const CodeIcon = (p: P) => (
  <Svg size={16} weight={1.8} {...p}>
    <path d="M16 18l6-6-6-6M8 6l-6 6 6 6" />
  </Svg>
)

/** Plan — 목록 */
export const PlanIcon = (p: P) => (
  <Svg size={16} weight={1.8} {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="M4 6h.01M4 12h.01M4 18h.01" strokeWidth={2.6} />
  </Svg>
)

/** Auto — 번개 */
export const BoltIcon = (p: P) => (
  <Svg size={16} weight={1.8} {...p}>
    <path d="M13 2L4 14h8l-1 8 9-12h-8l1-8z" />
  </Svg>
)

/** 음성 입력 — 마이크 */
export const MicIcon = (p: P) => (
  <Svg size={17} weight={1.8} {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M18.5 11a6.5 6.5 0 01-13 0M12 17.5V21" />
  </Svg>
)

/** 슬래시 명령 */
export const SlashIcon = (p: P) => (
  <Svg size={17} weight={1.8} {...p}>
    <path d="M15.5 4l-7 16" />
  </Svg>
)

/** 선택됨 · 완료 — 체크 */
export const CheckIcon = (p: P) => (
  <Svg size={14} weight={2.2} {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
)

/** 폴더 */
export const FolderIcon = (p: P) => (
  <Svg size={16} weight={1.7} {...p}>
    <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
  </Svg>
)

/** 경고 — 세모 느낌표 */
export const WarningIcon = (p: P) => (
  <Svg size={15} weight={1.9} {...p}>
    <path d="M10.3 4.2L2.5 18a2 2 0 001.7 3h15.6a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z" />
    <path d="M12 10v4M12 17.5h.01" />
  </Svg>
)

/** 이름 바꾸기 — 연필 */
export const PencilIcon = (p: P) => (
  <Svg size={15} weight={1.8} {...p}>
    <path d="M16.5 3.5a2.1 2.1 0 013 3L8 18l-4 1 1-4z" />
    <path d="M14 6l3 3" />
  </Svg>
)

/** 할 일 — 진행 중(꺾쇠) · 대기(빈 동그라미) */
export const ChevronRightIcon = (p: P) => (
  <Svg size={14} weight={2} {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
)

export const CircleIcon = (p: P) => (
  <Svg size={14} weight={1.8} {...p}>
    <circle cx="12" cy="12" r="7" />
  </Svg>
)
