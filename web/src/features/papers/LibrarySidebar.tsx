import type { CSSProperties } from 'react'
import type { Paper } from '@/api/types'
import { CollapsibleSidebar, IconButton, VisuallyHidden } from '@/components'
import { Skeleton } from '@/components/StateMessage'
import s from './LibrarySidebar.module.css'

export type LibraryView = 'recent' | 'all' | 'todo' | 'reading' | 'done' | 'trash' | `field:${string}` | `col:${string}`

const FIXED: Record<string, { title: string; test: (p: Paper) => boolean }> = {
  recent: { title: '최근 열어본 논문', test: () => true },
  all: { title: '전체 논문', test: () => true },
  todo: { title: '읽을 예정', test: (p) => p.status === 'todo' },
  reading: { title: '읽는 중', test: (p) => p.status === 'reading' },
  done: { title: '완료', test: (p) => p.status === 'done' },
  // 휴지통은 목록 자체가 달라요 (서버의 trash 목록) — 거르는 규칙은 모두 통과
  trash: { title: '휴지통', test: () => true },
}

/** 보기의 제목과 거르는 규칙. 분야(Research Field)는 vault 노트의 category에서 와요 */
export function libraryView(v: LibraryView): { title: string; test: (p: Paper) => boolean } {
  if (v.startsWith('col:')) {
    const name = v.slice('col:'.length)
    return { title: name, test: (p) => (p.collections ?? []).includes(name) }
  }
  if (v.startsWith('field:')) {
    const field = v.slice('field:'.length)
    return { title: `# ${field}`, test: (p) => p.field === field }
  }
  return FIXED[v] ?? FIXED.all
}

/** 분야 목록 — 많은 순 */
function fieldsOf(papers: Paper[] | undefined) {
  const n = new Map<string, number>()
  for (const p of papers ?? []) if (p.field) n.set(p.field, (n.get(p.field) ?? 0) + 1)
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([f]) => f)
}

interface Props {
  style: CSSProperties
  onCollapse: () => void
  papers: Paper[] | undefined
  view: LibraryView
  onViewChange: (v: LibraryView) => void
  search: string
  onSearchChange: (q: string) => void
  /** vault 위치 (없으면 아직 모름) */
  vaultPath?: string
  onVault: () => void
  /** lab.remote 모음 (vault는 그대로) */
  collections?: { name: string; count: number }[]
  onAddCollection?: () => void
  onRemoveCollection?: (name: string) => void
  trashCount?: number
}

export function LibrarySidebar({
  style,
  onCollapse,
  papers,
  view,
  onViewChange,
  search,
  onSearchChange,
  vaultPath,
  onVault,
  collections = [],
  onAddCollection,
  onRemoveCollection,
  trashCount,
}: Props) {
  /** 목업은 개수가 마크업에 박혀 있었어요. 여기서는 데이터로 세요 */
  const count = (id: LibraryView) => papers?.filter(libraryView(id).test).length ?? 0

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
        <IconButton label="모음 추가" variant="tint" onClick={onAddCollection}>
          <PlusIcon />
        </IconButton>
      </div>

      {item('all', '전체 논문')}
      {item('todo', '읽을 예정')}
      {item('reading', '읽는 중')}
      {item('done', '완료')}

      {collections.length > 0 && <span className={s.groupLabel}>모음</span>}
      {collections.map((c) => (
        <div key={c.name} className={s.colRow}>
          <button type="button" aria-pressed={view === `col:${c.name}`} onClick={() => onViewChange(`col:${c.name}`)} className={s.item}>
            <span className={s.label}>{c.name}</span>
            <span className={s.count}>{c.count}</span>
          </button>
          {onRemoveCollection && (
            <button type="button" aria-label={`${c.name} 모음 삭제`} title="모음만 삭제해요 (논문은 그대로 남아요)" className={s.colRemove} onClick={() => onRemoveCollection(c.name)}>
              ×
            </button>
          )}
        </div>
      ))}

      {fieldsOf(papers).length > 0 && <span className={s.groupLabel}>Research Field</span>}
      {fieldsOf(papers).map((f) => item(`field:${f}`, `# ${f}`))}

      <div className={s.footer}>
        <button type="button" className={s.item} onClick={onVault} title={vaultPath}>
          <FolderIcon />
          <span className={s.label}>vault 위치</span>
        </button>
        <button type="button" className={s.item} aria-pressed={view === 'trash'} onClick={() => onViewChange('trash')}>
          <TrashIcon />
          <span className={s.label}>휴지통</span>
          {!!trashCount && <span className={s.count}>{trashCount}</span>}
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
const FolderIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
  </svg>
)
const TrashIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </svg>
)
