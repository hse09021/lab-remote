import { Link } from 'react-router-dom'
import type { UseQueryResult } from '@tanstack/react-query'
import type { ProjectDetail, Worktree, WorktreeList } from '@/api/projects'
import { ErrorState, LoadingState } from '@/components'
import s from './Projects.module.css'

function aheadText(w: Worktree, main: string): string {
  if (w.primary || w.branch === main) return '—'
  if (w.merged) return `${main} 에 합쳐짐`
  const parts: string[] = []
  if (w.ahead) parts.push(`${w.ahead} 커밋 앞섬`)
  if (w.changed) parts.push(`변경 ${w.changed} (커밋 전)`)
  return parts.join(' · ') || '같음'
}

export function WorktreesTab({ project, trees }: { project: ProjectDetail; trees: UseQueryResult<WorktreeList> }) {
  if (trees.isPending) return <LoadingState label="worktree 를 불러오는 중이에요" />
  if (trees.isError) return <ErrorState error={trees.error} onRetry={() => trees.refetch()} />
  const data = trees.data
  if (data.state !== 'ok') {
    return <div className={s.notice}>{data.state === 'none' ? 'git 저장소가 아니라 worktree 가 없어요.' : data.reason}</div>
  }
  const ade = `/projects/${encodeURIComponent(project.name)}/ade`

  return (
    <div className={s.treesWrap}>
      <div className={s.treesHead}>
        <span className={s.muted}>
          작업마다 worktree 하나씩 · <span className={s.mono}>.labremote/worktrees/</span> 에 만들어요 (만들기는 ADE 단계에서)
        </span>
      </div>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.thFirst}>브랜치</th>
              <th>{data.main || 'main'} 대비</th>
              <th>세션</th>
              <th>경로</th>
              <th className={s.thLast}>동작</th>
            </tr>
          </thead>
          <tbody>
            {data.worktrees.map((w) => (
              <tr key={w.path}>
                <td className={`${s.tdFirst} ${s.monoCell}`}>{w.branch || `(분리됨 ${w.head})`}</td>
                <td>{aheadText(w, data.main)}</td>
                <td className={s.muted} title="세션은 3단계에서 붙어요">
                  —
                </td>
                <td className={s.monoCell}>{w.rel ?? w.path}</td>
                <td className={s.actions}>
                  {w.merged && (
                    <span className={s.staleTag} title="정리(지우기)는 사람이 누를 때만 — 다음 단계에서 붙어요">
                      정리 대상
                    </span>
                  )}
                  <Link to={ade} className={s.actLink}>
                    ADE
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
