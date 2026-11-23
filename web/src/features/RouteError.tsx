import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { isChunkError, reloadOnce } from '@/lib/lazyReload'

/** 화면에서 예상 못 한 오류 — 개발자용 기본 화면 대신 */
export default function RouteError() {
  const err = useRouteError()
  const chunk = isChunkError(err)
  if (chunk && reloadOnce()) return null
  const detail = isRouteErrorResponse(err) ? `${err.status} ${err.statusText}` : err instanceof Error ? err.message : String(err)
  return (
    <main style={{ padding: '40px 32px', display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
      <h1 style={{ margin: 0, fontSize: 20 }}>{chunk ? 'lab.remote가 새로 바뀌었어요' : '화면을 그리다 문제가 생겼어요'}</h1>
      <p style={{ margin: 0, fontSize: 14, color: 'var(--text-soft)', lineHeight: 1.6 }}>
        {chunk
          ? '이 탭은 바뀌기 전 화면을 들고 있어요. 새로 고침하면 새 화면을 받아요.'
          : '새로 고침해도 같으면 아래 내용을 알려 주세요.'}
      </p>
      <code style={{ fontSize: 12, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>{detail}</code>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{ alignSelf: 'flex-start', minHeight: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-md)', background: 'var(--bg)', cursor: 'pointer' }}
      >
        새로 고침
      </button>
    </main>
  )
}
