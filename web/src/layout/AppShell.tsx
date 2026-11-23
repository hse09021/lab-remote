import { Outlet } from 'react-router-dom'
import { AppHeader } from './AppHeader'
import s from './AppShell.module.css'

/**
 * 껍데기. v3 는 모바일 전용 화면이 아직 없어요(PLAN 7장) — 데스크톱 화면이
 * 좁은 폭에서 깨지지 않게만 해요. 헤더는 줄바꿈으로 버텨요.
 */
export function AppShell() {
  return (
    <div className={s.shell}>
      <AppHeader />
      <div className={s.body}>
        <Outlet />
      </div>
    </div>
  )
}
