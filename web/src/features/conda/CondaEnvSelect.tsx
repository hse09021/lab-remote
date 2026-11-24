import { useQuery } from '@tanstack/react-query'
import { condaEnvsQuery } from '@/api/conda'

/**
 * 이미 만든 conda 환경 중에서 선택해요 (실행 · 예약 · IDE 실행 탭).
 * conda 목록을 읽지 못하면 직접 입력할 수 있게 입력 칸으로 바뀌어요.
 */
export function CondaEnvSelect({
  value,
  onChange,
  className,
  id,
}: {
  value: string
  onChange: (env: string) => void
  className?: string
  id?: string
}) {
  const envs = useQuery(condaEnvsQuery())
  if (envs.isError) {
    return <input id={id} className={className} value={value} onChange={(e) => onChange(e.target.value)} placeholder="lora-env" aria-label="conda 환경" />
  }
  const names = (envs.data?.envs ?? []).map((e) => e.name)
  const current = value.trim()
  return (
    <select id={id} className={className} value={current} onChange={(e) => onChange(e.target.value)} aria-label="conda 환경" disabled={envs.isPending}>
      <option value="">conda 없이 실행</option>
      {current && !names.includes(current) && !envs.isPending && <option value={current}>{current} (목록에 없음)</option>}
      {current && envs.isPending && <option value={current}>{current}</option>}
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  )
}
