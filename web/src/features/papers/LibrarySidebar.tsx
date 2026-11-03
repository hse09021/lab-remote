import type { CSSProperties } from 'react'
import type { Paper } from '@/api/types'
import { CollapsibleSidebar, IconButton, VisuallyHidden } from '@/components'
import { Skeleton } from '@/components/StateMessage'
import s from './LibrarySidebar.module.css'

export type LibraryView =
  | 'recent'
  | 'all'
  | 'todo'
  | 'reading'
  | 'done'
  | 'peft'
  | 'vision'
  | 'nlp'

/** 목업의 VIEWS. 제목과 거르는 규칙을 한 곳에 뒀어요 */
export const LIBRARY_VIEWS: Record<
  LibraryView,
  { title: string; test: (p: Paper) => boolean }
> = {
  recent: { title: '최근 열어본 논문', test: () => true },
  all: { title: '전체 논문', test: () => true },
  todo: { title: '읽을 예정', test: (p) => p.status === 'todo' },
  reading: { title: '읽는 중', test: (p) => p.status === 'reading' },
  done: { title: '완료', test: (p) => p.status === 'done' },
  peft: { title: '# PEFT', test: (p) => p.field === 'PEFT' },
  vision: { title: '# Vision', test: (p) => p.field === 'Vision' },
  nlp: { title: '# NLP', test: (p) => p.field === 'NLP' },
}

interface Props {
  style: CSSProperties
  onCollapse: () => void
  papers: Paper[] | undefined
  view: LibraryView
  onViewChange: (v: LibraryView) => void
  search: string
  onSearchChange: (q: string) => void
}

export function LibrarySidebar({
  style,
  onCollapse,
  papers,
  view,
  onViewChange,
  search,
  onSearchChange,
}: Props) {
  /** 목업은 개수가 마크업에 박혀 있었어요. 여기서는 데이터로 세요 */
  const count = (id: LibraryView) => papers?.filter(LIBRARY_VIEWS[id].test).length ?? 0

  const item = (id: LibraryView, label: string, showCount = true) => (
    <button
      key={id}
      type="button"
      aria-pressed={view === id}
      onClick={() => onViewChange(id)}
      className={s.item}
    >
      <span className={s.label}>{label}</span>
      {showCount &&
        (papers ? <span className={s.count}>{count(id)}</span> : <Skeleton width={14} height={14} />)}
    </button>
  )

  return (
    <CollapsibleSidebar
      label="라이브러리 메뉴"
      style={style}
      onCollapse={onCollapse}
      showCollapseButton={false}
      className={s.panel}
    >
      <div className={s.collapseRow}>
        <IconButton label="사이드바 접기" aria-expanded onClick={onCollapse}>
          <PanelIcon />
        </IconButton>
      </div>

      <button
        type="button"
        aria-pressed={view === 'recent'}
        onClick={() => onViewChange('recent')}
        className={s.item}
      >
        <ClockIcon />
        <span className={s.label}>최근 열어본 논문</span>
      </button>

      <VisuallyHidden>
        <label htmlFor="lib-search">라이브러리 검색</label>
      </VisuallyHidden>
      <div className={s.search}>
        <SearchIcon />
        <input
          id="lib-search"
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="라이브러리 검색"
          className={s.searchInput}
        />
      </div>

      <div className={s.sectionRow}>
        <span className={s.sectionTitle}>
          <BookIcon />
          라이브러리
        </span>
        <IconButton label="폴더 추가" variant="tint">
          <PlusIcon />
        </IconButton>
      </div>

      {item('all', '전체 논문')}
      {item('todo', '읽을 예정')}
      {item('reading', '읽는 중')}
      {item('done', '완료')}

      <span className={s.groupLabel}>Research Field</span>
      {item('peft', '# PEFT')}
      {item('vision', '# Vision')}
      {item('nlp', '# NLP')}

      <div className={s.footer}>
        <button type="button" className={s.item}>
          <TrashIcon />
          휴지통
        </button>
      </div>
    </CollapsibleSidebar>
  )
}

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

const PanelIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </svg>
)
const ClockIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </svg>
)
const SearchIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </svg>
)
const BookIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5z" />
    <path d="M4 19a2 2 0 012-2h13" />
  </svg>
)
const PlusIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.2"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M12 5v14M5 12h14" />
  </svg>
)
const TrashIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </svg>
)
