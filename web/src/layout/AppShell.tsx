import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { accountQuery } from '@/api/agents'
import { badgeQuery } from '@/api/inbox'
import { healthQuery } from '@/api/system'
import { useIsMobile } from '@/lib/useMediaQuery'
import { AppHeader } from './AppHeader'
import { useServerEvents } from '@/lib/useServerEvents'
import s from './AppShell.module.css'

/**
 * 껍데기. 휴대폰(768px 이하)에서는 헤더를 한 줄로 줄이고 아래에 탭 막대를 둬요 (PLAN 7장:
 * 답 필요 + 승인, 실행 · 예약, Inbox 중심).
 * 서버에 닿지 않거나 Claude Code 로그인이 풀렸으면 맨 위에 안내 띠를 보여요.
 */
export function AppShell() {
  // 세션 메시지 · 승인 · 알림을 실시간으로 받아요 (SSE 하나)
  useServerEvents()
  const mobile = useIsMobile()
  const health = useQuery(healthQuery())
  const account = useQuery({ ...accountQuery(), enabled: health.isSuccess })
  const badge = useQuery(badgeQuery())
  const down = health.isError
  const loginNeeded = account.data && (account.data.installed === false || account.data.loggedIn === false)

  return (
    <div className={s.shell} data-mobile={mobile}>
      <AppHeader />
      {down && (
        <div role="alert" className={s.banner} data-tone="bad">
          서버에 연결되지 않아 다시 연결하는 중이에요. 계속 연결되지 않으면 데스크톱에서 <code>labremote autostart status</code>로 확인해 주세요.
        </div>
      )}
      {!down && loginNeeded && (
        <div role="alert" className={s.banner} data-tone="warn">
          {account.data?.installed === false
            ? 'Claude Code가 설치되어 있지 않아 채팅, 요약 같은 AI 기능을 사용할 수 없어요. 데스크톱에 설치하고 로그인해 주세요.'
            : 'Claude Code에서 로그아웃되어 채팅, 요약 같은 AI 기능을 사용할 수 없어요. 데스크톱 터미널에서 claude를 실행하고 /login으로 다시 로그인해 주세요.'}
        </div>
      )}
      <div className={s.body}>
        <Outlet />
      </div>
      {mobile && (
        <nav aria-label="주 메뉴" className={s.tabs}>
          <NavLink to="/dashboard" className={s.tab}>
            홈
          </NavLink>
          <NavLink to="/projects" className={s.tab}>
            Projects
          </NavLink>
          <NavLink to="/papers" className={s.tab}>
            Papers
          </NavLink>
          <NavLink to="/inbox" className={s.tab}>
            Inbox
            {!!badge.data?.badge && <span className={s.tabBadge}>{badge.data.badge}</span>}
          </NavLink>
        </nav>
      )}
    </div>
  )
}
