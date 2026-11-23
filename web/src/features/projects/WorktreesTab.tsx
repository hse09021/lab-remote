import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { sessionsQuery } from '@/api/agents'
import { ApiError } from '@/api/client'
import { useAddWorktree, useRemoveWorktree } from '@/api/projects'
import type { ProjectDetail, Worktree, WorktreeList } from '@/api/projects'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import s from './Projects.module.css'

function aheadText(w: Worktree, main: string): string {
  if (w.primary || w.branch === main) return '—'
  if (w.merged) return `${main} 에 합쳐짐`
  const parts: string[] = []
  if (w.ahead) parts.push(`${w.ahead} 커밋 앞섬`)
  if (w.changed) parts.push(`변경 ${w.changed} (커밋 전)`)
  return parts.join(' · ') || '같음'
}

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : undefined)

/** lab.remote 가 만든 worktree 만 정리할 수 있어요 */
const ours = (w: Worktree) => !w.primary && (w.rel ?? '').startsWith('.labremote/worktrees/')

export function WorktreesTab({ project, trees }: { project: ProjectDetail; trees: UseQueryResult<WorktreeList> }) {
  const sessions = useQuery(sessionsQuery())
  const [adding, setAdding] = useState(false)
  const [cleaning, setCleaning] = useState<Worktree | null>(null)

  if (trees.isPending) return <LoadingState label="worktree 를 불러오는 중이에요" />
  if (trees.isError) return <ErrorState error={trees.error} onRetry={() => trees.refetch()} />
  const data = trees.data
  if (data.state !== 'ok') {
    return <div className={s.notice}>{data.state === 'none' ? 'git 저장소가 아니라 worktree 가 없어요.' : data.reason}</div>
  }
  const ade = `/projects/${encodeURIComponent(project.name)}/ade`
  const mine = (sessions.data?.sessions ?? []).filter((x) => x.project === project.name)
  const sessionsOf = (w: Worktree) => mine.filter((x) => x.tree === (w.primary ? '.' : w.rel))

  return (
    <div className={s.treesWrap}>
      <div className={s.treesHead}>
        <span className={s.muted}>작업마다 worktree 하나씩 · ADE 에서 세션을 만들면 함께 생겨요</span>
        <button type="button" className={s.primaryBtn} onClick={() => setAdding(true)}>
          + worktree
        </button>
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
            {data.worktrees.map((w) => {
              const here = sessionsOf(w)
              const tree = w.primary ? '' : (w.rel ?? '')
              return (
                <tr key={w.path}>
                  <td className={`${s.tdFirst} ${s.monoCell}`}>{w.branch || `(분리됨 ${w.head})`}</td>
                  <td>{aheadText(w, data.main)}</td>
                  <td className={here.length ? undefined : s.muted}>
                    {here.length ? `${here.length}개 · ${here[0].stateLabel}` : '—'}
                  </td>
                  <td className={s.monoCell}>{w.rel ?? w.path}</td>
                  <td className={s.actions}>
                    {w.merged && ours(w) && (
                      <button type="button" className={s.actBtn} onClick={() => setCleaning(w)}>
                        정리…
                      </button>
                    )}
                    {w.rel !== null && (
                      <Link to={tree ? `${ade}?tree=${encodeURIComponent(tree)}` : ade} className={s.actLink}>
                        ADE
                      </Link>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className={`${s.muted} ${s.treesFoot}`}>
        정리는 {data.main || 'main'} 에 합쳐진 worktree 에만 나와요. 폴더만 지우고 브랜치는 남겨요.
      </p>
      <AddDialog name={project.name} open={adding} onClose={() => setAdding(false)} />
      {cleaning && <CleanDialog name={project.name} tree={cleaning} onClose={() => setCleaning(null)} />}
    </div>
  )
}

function AddDialog({ name, open, onClose }: { name: string; open: boolean; onClose: () => void }) {
  const add = useAddWorktree(name)
  const [branch, setBranch] = useState('')
  const close = () => {
    add.reset()
    setBranch('')
    onClose()
  }
  return (
    <Dialog
      open={open}
      title="새 worktree"
      confirmLabel="만들기"
      busy={add.isPending}
      error={errText(add.error)}
      onClose={close}
      onConfirm={() => add.mutate({ branch: branch.trim() }, { onSuccess: close })}
    >
      <label className={ds.field}>
        브랜치 이름
        <input className={ds.input} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="exp/early-stop" autoFocus />
      </label>
      <span>
        <span className={s.mono}>.labremote/worktrees/</span> 에 만들어요. 브랜치가 없으면 지금 위치에서 새로 만들어요.
      </span>
    </Dialog>
  )
}

function CleanDialog({ name, tree, onClose }: { name: string; tree: Worktree; onClose: () => void }) {
  const remove = useRemoveWorktree(name)
  return (
    <Dialog
      open
      title={`${tree.branch} 정리`}
      confirmLabel="정리"
      tone="danger"
      busy={remove.isPending}
      error={errText(remove.error)}
      onClose={onClose}
      onConfirm={() => remove.mutate({ rel: tree.rel ?? '' }, { onSuccess: onClose })}
    >
      <span>
        <span className={s.mono}>{tree.rel}</span> 폴더를 지워요. 브랜치 <span className={s.mono}>{tree.branch}</span> 는 남아서
        다시 만들 수 있어요.
      </span>
      <span>커밋 안 한 변경이 있거나 이 worktree 에서 학습 · 세션이 돌고 있으면 정리하지 않아요.</span>
    </Dialog>
  )
}
