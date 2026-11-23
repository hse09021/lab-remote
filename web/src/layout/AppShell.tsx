import { Outlet } from 'react-router-dom'
import { AppHeader } from './AppHeader'
import { useServerEvents } from '@/lib/useServerEvents'
import s from './AppShell.module.css'

/**
 * 껍데기. v3 는 모바일 전용 화면이 아직 없어요(PLAN 7장) — 데스크톱 화면이
 * 좁은 폭에서 깨지지 않게만 해요. 헤더는 줄바꿈으로 버텨요.
 */
export function AppShell() {
  // 세션 메시지 · 승인 · 알림을 실시간으로 받아요 (SSE 하나)
  useServerEvents()
  return (
    <div className={s.shell}>
      <AppHeader />
      <div className={s.body}>
        <Outlet />
      </div>
    </div>
  )
}
