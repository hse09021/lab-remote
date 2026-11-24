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
      <h1 style={{ margin: 0, fontSize: 20 }}>{chunk ? 'lab.remote가 업데이트됐어요' : '화면을 표시하다가 문제가 생겼어요'}</h1>
      <p style={{ margin: 0, fontSize: 14, color: 'var(--text-soft)', lineHeight: 1.6 }}>
        {chunk
          ? '이 탭에는 업데이트 전 화면이 남아 있어요. 새로 고침하면 최신 화면을 불러와요.'
          : '새로 고침해도 계속되면 아래 내용을 알려 주세요.'}
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
