import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from './layout/AppShell'
import NotFound from './features/NotFound'

import PapersLibrary from './features/papers/PapersLibrary'
import PaperReader from './features/papers/PaperReader'
import ExperimentDashboard from './features/experiments/ExperimentDashboard'
import PermissionSettings from './features/experiments/PermissionSettings'
import ExperimentDesignDraft from './features/experiments/ExperimentDesignDraft'

// 코드 화면만 따로 떼요 — Monaco가 무거워서 다른 화면 번들에 섞이면 안 돼요.
const CodeEditorPage = lazy(() => import('./features/code/CodeEditorPage'))

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/experiments" replace /> },

      { path: 'papers', element: <PapersLibrary /> },
      { path: 'papers/:id', element: <PaperReader /> },

      { path: 'experiments', element: <ExperimentDashboard /> },
      { path: 'experiments/permissions', element: <PermissionSettings /> },
      { path: 'experiments/new/from-paper', element: <ExperimentDesignDraft /> },

      {
        path: 'code',
        element: (
          <Suspense fallback={<ScreenLoading />}>
            <CodeEditorPage />
          </Suspense>
        ),
      },

      { path: '*', element: <NotFound /> },
    ],
  },
])

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
