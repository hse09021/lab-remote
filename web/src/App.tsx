import { Suspense } from 'react'
import type { ReactNode } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from './layout/AppShell'
import NotFound from './features/NotFound'
import RouteError from './features/RouteError'
import { lazyReload } from './lib/lazyReload'

import PapersLibrary from './features/papers/PapersLibrary'
import PaperReader from './features/papers/PaperReader'
import ProjectsPage from './features/projects/ProjectsPage'
import SystemPage from './features/system/SystemPage'
import DashboardPage from './features/dashboard/DashboardPage'
import InboxPage from './features/inbox/InboxPage'
import AdePage from './features/agents/AdePage'
import CondaPage from './features/conda/CondaPage'

// IDE 만 따로 떼요 — Monaco가 무거워서 다른 화면 번들에 섞이면 안 돼요.
// 새로 빌드돼 옛 조각 파일이 없으면 한 번 새로 고쳐요 (lazyReload)
const IdePage = lazyReload(() => import('./features/ide/IdePage'))

/** 라우트 — docs/v3/PLAN.md 4.2 */
const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },

      { path: 'dashboard', element: <DashboardPage /> },

      { path: 'projects', element: <ProjectsPage /> },
      { path: 'projects/:id', element: <ProjectsPage /> },
      { path: 'projects/:id/ide', element: <Lazy><IdePage /></Lazy> },
      { path: 'projects/:id/ade', element: <AdePage /> },

      { path: 'papers', element: <PapersLibrary /> },
      { path: 'papers/:id', element: <PaperReader /> },

      { path: 'inbox', element: <InboxPage /> },

      { path: 'settings/conda', element: <CondaPage /> },
      { path: 'settings/system', element: <SystemPage /> },

      // v1 주소 — 북마크가 깨지지 않게
      { path: 'experiments', element: <Navigate to="/dashboard" replace /> },
      { path: 'code', element: <Navigate to="/projects" replace /> },

      { path: '*', element: <NotFound /> },
    ],
  },
])

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<ScreenLoading />}>{children}</Suspense>
}

function ScreenLoading() {
  return (
    <div
      role="status"
      style={{ flex: 1, padding: '28px 32px', fontSize: 13, color: 'var(--text-muted)' }}
    >
      불러오는 중이에요…
    </div>
  )
}

export function App() {
  return <RouterProvider router={router} />
}
