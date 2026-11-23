import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './styles/fonts'
import './styles/tokens.css'
import './styles/reset.css'

import { App } from './App'
import { resetMockFromUrl } from './api/client'

// 주소에 ?reset-mock이 있으면 목업 저장소를 비우고 시작해요 (개발 모드)
resetMockFromUrl()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('#root를 찾지 못했어요')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
