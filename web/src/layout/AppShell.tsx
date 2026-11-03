import { Outlet } from 'react-router-dom'
import { AppHeader } from './AppHeader'
import s from './AppShell.module.css'

/**
 * 데스크톱 껍데기. 상단 바 + 화면 전체 폭을 쓰는 본문.
 * 모바일 껍데기(MobileShell)는 2단계 마지막에 붙여요.
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
