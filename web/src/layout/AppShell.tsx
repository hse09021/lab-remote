import { Outlet } from 'react-router-dom'
import { useIsMobile } from '@/lib/useMediaQuery'
import { AppHeader } from './AppHeader'
import { MobileShell } from './MobileShell'
import s from './AppShell.module.css'

/**
 * 껍데기. 768px 이하에서는 모바일 껍데기로 갈아끼워요 —
 * 라우트는 그대로고 레이아웃만 달라져요.
 */
export function AppShell() {
  const isMobile = useIsMobile()
  if (isMobile) return <MobileShell />

  return (
    <div className={s.shell}>
      <AppHeader />
      <div className={s.body}>
        <Outlet />
      </div>
    </div>
  )
}
