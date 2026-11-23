import { useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { gpuQuery, healthQuery } from '@/api/system'
import { badgeQuery } from '@/api/inbox'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './AppHeader.module.css'

/** 전역 헤더 한 줄 (PLAN 4.2 · 목업 공통 헤더) */
const TABS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/projects', label: 'Projects' },
  { to: '/papers', label: 'Papers' },
  { to: '/inbox', label: 'Inbox' },
] as const

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

export function AppHeader() {
  const gpu = useQuery(gpuQuery())
  const health = useQuery(healthQuery())
  const badge = useQuery(badgeQuery())
  const inboxCount = badge.data?.badge ?? 0

  // 목업의 "Tunnel" 점 — 서버에 닿으면 터널 상태를, 못 닿으면 "서버 끊김" 을 보여 줘요
  const connected = health.isSuccess
  const tunnelUp = health.data?.tunnel === 'up'
  const connLabel = health.isPending ? '연결 확인 중' : !connected ? '서버 끊김' : 'Tunnel'
  const connTitle = !connected
    ? 'lab.remote 서버에 닿지 않아요'
    : tunnelUp
      ? 'code tunnel 이 켜져 있어요'
      : 'code tunnel 이 꺼져 있어요 — 이 데스크톱에서만 열려요'

  return (
    <header className={s.header}>
      <div className={s.inner}>
        <Link to="/dashboard" className={s.wordmark}>
          lab<span className={s.dot}>.</span>remote
        </Link>

        <nav aria-label="주 메뉴" className={s.nav}>
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} className={s.tab}>
              {tab.label}
              {/* 배지는 "내가 처리해야 하는 것"(답 필요 · 실행 실패·끊김) 중 안 읽은 것만 (2026-11-23 결정) */}
              {tab.to === '/inbox' && inboxCount > 0 && (
                <span className={s.badge} aria-label={`처리할 알림 ${inboxCount}`}>
                  {inboxCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className={s.right}>
          <button
            type="button"
            className={s.goto}
            aria-label={`Go to, ${isMac ? '⌘' : 'Ctrl+'}K`}
            title="검색 창은 아직 없어요"
            disabled
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <circle cx="11" cy="11" r="6" />
              <path d="m20 20-4.5-4.5" />
            </svg>
            <span className={s.gotoText}>Go to…</span>
            <kbd className={s.kbd}>{isMac ? '⌘K' : 'Ctrl K'}</kbd>
          </button>

          <span className={s.gpu} title={gpu.data?.reason || undefined}>
            {gpu.data?.label ?? (gpu.isError ? 'GPU —' : 'GPU …')}
          </span>

          <Link to="/settings/system" className={s.conn} title={connTitle}>
            <span aria-hidden="true" className={s.connDot} data-tone={!connected ? 'off' : tunnelUp ? 'ok' : 'idle'} />
            {connLabel}
          </Link>

          <SettingsMenu />
        </div>
      </div>
    </header>
  )
}

function SettingsMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useOutsideClick(ref, () => setOpen(false), open)

  return (
    <div ref={ref} className={s.menuWrap}>
      <button
        type="button"
        className={s.gear}
        aria-label="Conda · System 메뉴"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
      </button>
      {open && (
        <div role="menu" aria-label="Conda · System" className={s.menu}>
          <Link role="menuitem" to="/settings/conda" className={s.menuItem} onClick={() => setOpen(false)}>
            <span className={s.menuTitle}>Conda</span>
            <span className={s.menuSub}>환경 만들기 · 패키지 관리</span>
          </Link>
          <Link role="menuitem" to="/settings/system" className={s.menuItem} onClick={() => setOpen(false)}>
            <span className={s.menuTitle}>System</span>
            <span className={s.menuSub}>서버 · 터널 · 자동 시작 · 삭제</span>
          </Link>
        </div>
      )}
    </div>
  )
}
