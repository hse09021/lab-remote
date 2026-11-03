import { useQuery } from '@tanstack/react-query'
import { permissionsQuery } from '@/api/experiments'
import { useSavePermissions } from '@/api/permissions'
import type { PermissionMode } from '@/api/types'
import { ErrorState, LoadingState, Toast } from '@/components'
import { useToast } from '@/lib/useToast'
import s from './Mobile.module.css'

/**
 * 모바일 권한 화면.
 * 프리셋은 고를 수 있고 항목별 권한은 읽기만 해요 (PC에서 바꿔요).
 */
export function MobilePermissions() {
  const permissions = useQuery(permissionsQuery())
  const savePermissions = useSavePermissions()
  const toast = useToast(2600)

  if (permissions.isPending) return <LoadingState label="권한 설정을 불러오는 중이에요…" />
  if (permissions.isError || !permissions.data) {
    return (
      <ErrorState
        title="권한 설정을 불러오지 못했어요"
        error={permissions.error}
        onRetry={() => void permissions.refetch()}
      />
    )
  }

  const data = permissions.data
  const mode: PermissionMode = data.saved?.mode ?? 'full'

  return (
    <div className={s.page}>
      <div role="radiogroup" aria-label="권한 프리셋" className={s.modeList}>
        {data.modes.map((m) => (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={mode === m.id}
            onClick={() => {
              savePermissions.mutate({ mode: m.id, overrides: {} })
              toast.show('다음 작업부터 적용돼요')
            }}
            className={s.modeOption}
          >
            <span aria-hidden="true" className={s.radio} />
            <span className={s.modeText}>
              <span className={s.modeName}>{m.name}</span>
              <span className={s.modeDesc}>{m.desc}</span>
            </span>
          </button>
        ))}
      </div>

      <section className={s.card} aria-label="행동별 권한">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>행동별 권한</span>
          <span className={s.cardNote}>보기 전용</span>
        </div>
        <ul className={s.queue}>
          {data.actions.map((a) => {
            const value = a.defaults[mode]
            return (
              <li key={a.key} className={s.readRow}>
                <span className={s.readValue}>
                  {a.name}
                  {a.locked && <span className={s.sheetNote}> · 잠김</span>}
                </span>
                <span data-tone={toneOf(value)} className={s.badge}>
                  {data.labels[value]}
                </span>
              </li>
            )
          })}
        </ul>
        <span className={s.sheetNote}>항목별 권한은 PC에서 바꿔요.</span>
      </section>

      <Toast message={toast.message} placement="bottom" />
    </div>
  )
}

const toneOf = (v: string) => (v === 'allow' ? 'success' : v === 'block' ? 'solid' : 'warn')
