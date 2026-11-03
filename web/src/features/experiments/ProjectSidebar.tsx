import { NavLink } from 'react-router-dom'
import type { CSSProperties } from 'react'
import type { ProjectsPayload } from '@/api/types'
import { CollapsibleSidebar, IconButton } from '@/components'
import { Skeleton } from '@/components/StateMessage'
import s from './ProjectSidebar.module.css'

/**
 * 사이드바를 못 불러와도 화면 사이 이동은 막히면 안 돼요.
 * 경로는 라우터와 같은 값이라 서버 응답 없이도 안전해요.
 */
const FALLBACK_VIEWS = [
  { id: 'dashboard', label: '대시보드', to: '/experiments', icon: 'grid' as const },
  { id: 'permissions', label: '권한 설정', to: '/experiments/permissions', icon: 'shield' as const },
]

interface Props {
  style: CSSProperties
  onCollapse: () => void
  data: ProjectsPayload | undefined
  /** 못 불러왔으면 스켈레톤 대신 안내를 보여줘요 */
  isError?: boolean
}

/**
 * 실험 화면(대시보드·권한 설정)이 함께 쓰는 왼쪽 사이드바.
 * 크기 조절은 usePaneResize + Resizer가 맡고, 접기 토글만 여기로 받아요.
 */
export function ProjectSidebar({ style, onCollapse, data, isError = false }: Props) {
  return (
    <CollapsibleSidebar
      label="실험 메뉴"
      style={style}
      onCollapse={onCollapse}
      showCollapseButton={false}
      className={s.panel}
    >
      <div className={s.sectionRow}>
        <span className={s.sectionLabel}>프로젝트</span>
        <div className={s.sectionActions}>
          <IconButton label="새 프로젝트" variant="tint">
            <PlusIcon />
          </IconButton>
          <IconButton label="사이드바 접기" aria-expanded onClick={onCollapse}>
            <PanelIcon />
          </IconButton>
        </div>
      </div>

      {data ? (
        data.projects.map((p, i) => (
          <a
            key={p.id}
            href={`#${p.id}`}
            aria-current={i === 0 ? 'page' : undefined}
            className={s.item}
          >
            <span aria-hidden="true" data-running={p.running} className={s.dot} />
            <span title={p.name} className={s.name}>
              {p.name}
            </span>
            <span data-running={p.running} className={s.state}>
              {p.stateLabel}
            </span>
          </a>
        ))
      ) : isError ? (
        <span className={s.failed}>프로젝트를 불러오지 못했어요</span>
      ) : (
        <SidebarSkeleton rows={2} />
      )}

      <span className={s.groupLabel}>보기</span>

      {data ? (
        data.views.map((v) => (
          <NavLink key={v.id} to={v.to} end className={s.item}>
            {v.icon === 'grid' ? <GridIcon /> : <ShieldIcon />}
            <span className={s.viewLabel}>{v.label}</span>
            {v.badge && <span className={s.badge}>{v.badge}</span>}
          </NavLink>
        ))
      ) : isError ? (
        FALLBACK_VIEWS.map((v) => (
          <NavLink key={v.id} to={v.to} end className={s.item}>
            {v.icon === 'grid' ? <GridIcon /> : <ShieldIcon />}
            <span className={s.viewLabel}>{v.label}</span>
          </NavLink>
        ))
      ) : (
        <SidebarSkeleton rows={2} />
      )}

      <div className={s.footer}>
        {isError ? (
          <span className={s.failed}>연결 상태를 알 수 없어요</span>
        ) : data
          ? data.integrations.map((it) => (
              <span key={it.label} className={s.integration}>
                <span aria-hidden="true" data-ok={it.ok} className={s.smallDot} />
                {it.label}
              </span>
            ))
          : [0, 1, 2].map((i) => <Skeleton key={i} height={14} width="80%" />)}
      </div>
    </CollapsibleSidebar>
  )
}

function SidebarSkeleton({ rows }: { rows: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={44} />
      ))}
    </>
  )
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

function PlusIcon() {
  return (
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
}

function PanelIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </svg>
  )
}

function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  )
}

function ShieldIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...stroke} aria-hidden="true">
      <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" />
    </svg>
  )
}
