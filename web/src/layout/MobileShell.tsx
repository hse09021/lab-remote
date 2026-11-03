import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dashboardQuery } from '@/api/experiments'
import s from './MobileShell.module.css'

const TABS = [
  { to: '/papers', label: '논문', icon: <PaperIcon /> },
  { to: '/experiments', label: '실험', icon: <GridIcon /> },
  { to: '/code', label: '코드', icon: <CodeIcon /> },
]

/** 지금 어느 탭인지 — 하위 경로(/papers/:id)도 같은 탭이에요 */
function tabOf(pathname: string) {
  if (pathname.startsWith('/papers')) return '논문'
  if (pathname.startsWith('/code')) return '코드'
  return '실험'
}

/**
 * 모바일 껍데기 (768px 이하).
 * 목업의 390×844 고정 프레임은 100dvh + safe-area 로 바꿨어요.
 */
export function MobileShell() {
  const { pathname } = useLocation()
  const dashboard = useQuery(dashboardQuery())
  const approvals = dashboard.data?.approval?.count ?? 0

  return (
    <div className={s.shell}>
      <header className={s.header}>
        <span className={s.wordmark}>
          lab<span className={s.dot}>.</span>remote
        </span>
        <span className={s.tabName}>{tabOf(pathname)}</span>
        <span className={s.conn}>
          <span aria-hidden="true" className={s.connDot} />
          연결 정상
        </span>
      </header>

      <main className={s.body}>
        <Outlet />
      </main>

      <nav aria-label="주 메뉴" className={s.tabs}>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) => (isActive ? `${s.tab} ${s.tabOn}` : s.tab)}
          >
            <span className={s.iconWrap}>
              {t.icon}
              {t.label === '실험' && approvals > 0 && (
                <span aria-hidden="true" className={s.badge}>
                  {approvals}
                </span>
              )}
            </span>
            {t.label}
            {t.label === '실험' && approvals > 0 && (
              <span className={s.srOnly}>승인 대기 {approvals}건</span>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

/* ── 아이콘 (목업 svg 그대로) ─────────────────────────────── */

function Svg({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

function PaperIcon() {
  return (
    <Svg>
      <path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5z" />
      <path d="M4 19a2 2 0 012-2h13" />
    </Svg>
  )
}

function GridIcon() {
  return (
    <Svg>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Svg>
  )
}

function CodeIcon() {
  return (
    <Svg>
      <path d="M8 8l-4 4 4 4M16 8l4 4-4 4" />
    </Svg>
  )
}
