import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from './layout/AppShell'
import NotFound from './features/NotFound'

import PapersLibrary from './features/papers/PapersLibrary'
import PaperReader from './features/papers/PaperReader'
import ProjectsPage from './features/projects/ProjectsPage'
import SystemPage from './features/system/SystemPage'
import { AdeShell, CondaShell, DashboardShell, InboxShell } from './features/shells'

// IDE 만 따로 떼요 — Monaco가 무거워서 다른 화면 번들에 섞이면 안 돼요.
const CodeEditorPage = lazy(() => import('./features/code/CodeEditorPage'))

/** 라우트 — docs/v3/PLAN.md 4.2 */
const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },

      { path: 'dashboard', element: <DashboardShell /> },

      { path: 'projects', element: <ProjectsPage /> },
      { path: 'projects/:id', element: <ProjectsPage /> },
      { path: 'projects/:id/ide', element: <Lazy><CodeEditorPage /></Lazy> },
      { path: 'projects/:id/ade', element: <AdeShell /> },

      { path: 'papers', element: <PapersLibrary /> },
      { path: 'papers/:id', element: <PaperReader /> },

      { path: 'inbox', element: <InboxShell /> },

      { path: 'settings/conda', element: <CondaShell /> },
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
