import { NavLink } from 'react-router-dom'
import s from './AppHeader.module.css'

/** 상단 메뉴 순서는 논문 · 실험 · 코드 (docs/HANDOFF.md 2절) */
const TABS = [
  { to: '/papers', label: '논문' },
  { to: '/experiments', label: '실험' },
  { to: '/code', label: '코드' },
] as const

interface Props {
  connectionLabel?: string
  connectionTone?: 'ok' | 'idle'
}

export function AppHeader({
  connectionLabel = '모든 연결 정상',
  connectionTone = 'ok',
}: Props) {
  return (
    <header className={s.header}>
      <div className={s.inner}>
        <span className={s.wordmark}>
          lab<span className={s.dot}>.</span>remote
        </span>

        <nav aria-label="주 메뉴" className={s.nav}>
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} className={s.tab}>
              {tab.label}
            </NavLink>
          ))}
        </nav>

        <div className={s.status}>
          <span aria-hidden="true" data-tone={connectionTone} className={s.statusDot} />
          {connectionLabel}
        </div>
      </div>
    </header>
  )
}
