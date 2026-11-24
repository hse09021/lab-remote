import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { dirQuery, gitStatusQuery, useMakeEntry } from '@/api/projects'
import type { ProjectDetail } from '@/api/projects'
import { gitCapsQuery, searchQuery, useGitAction } from '@/api/ide'
import { runsQuery, useStartRun, useStopRun } from '@/api/runs'
import { ApiError } from '@/api/client'
import { Dialog } from '@/components'
import { CollapseAllIcon, NewFileIcon, NewFolderIcon, RefreshIcon } from '@/components/icons'
import { RunStatePill } from '../projects/RunsTab'
import { ScheduleDialog } from '../schedule/ScheduleDialog'
import { duration, whenShort } from '@/lib/time'
import s from './Ide.module.css'

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : '')

/* ── 탐색기 ─────────────────────────────────────────────────── */

export function Explorer({ project, tree, label, onOpen }: { project: string; tree: string; label: string; onOpen: (path: string) => void }) {
  const [making, setMaking] = useState<'' | 'file' | 'dir'>('')
  const [name, setName] = useState('')
  // 모두 접기 — 폴더 트리를 처음 상태로 다시 그려요
  const [fold, setFold] = useState(0)
  const make = useMakeEntry(project)
  const qc = useQueryClient()
  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>탐색기</span>
        <button type="button" className={s.iconBtn} aria-label="새 파일" title="새 파일" onClick={() => setMaking('file')}>
          <NewFileIcon />
        </button>
        <button type="button" className={s.iconBtn} aria-label="새 폴더" title="새 폴더" onClick={() => setMaking('dir')}>
          <NewFolderIcon />
        </button>
        <button
          type="button"
          className={s.iconBtn}
          aria-label="탐색기 새로 고침"
          title="새로 고침"
          onClick={() => qc.invalidateQueries({ queryKey: ['projects', project, 'files'] })}
        >
          <RefreshIcon />
        </button>
        <button type="button" className={s.iconBtn} aria-label="모두 접기" title="모두 접기" onClick={() => setFold((n) => n + 1)}>
          <CollapseAllIcon />
        </button>
      </div>
      <div className={s.muted}>{label}</div>
      {making && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const path = name.trim()
            if (!path) return
            make.mutate(
              { tree, path, kind: making },
              {
                onSuccess: () => {
                  if (making === 'file') onOpen(path)
                  setMaking('')
                  setName('')
                },
              },
            )
          }}
        >
          <input
            className={s.input}
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setMaking('')}
            placeholder={making === 'file' ? 'src/new.py' : 'configs/new'}
            aria-label={making === 'file' ? '새 파일 경로' : '새 폴더 경로'}
          />
          <div className={s.muted}>Enter로 만들기 · Esc로 취소 {make.error ? `· ${errText(make.error)}` : ''}</div>
        </form>
      )}
      <Folder key={fold} project={project} tree={tree} path="" depth={0} onOpen={onOpen} />
    </div>
  )
}

function Folder({ project, tree, path, depth, onOpen }: { project: string; tree: string; path: string; depth: number; onOpen: (p: string) => void }) {
  const dir = useQuery(dirQuery(project, tree, path))
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (dir.isPending) return <div className={s.muted} style={{ paddingLeft: depth * 12 }}>…</div>
  if (dir.isError) return <div className={s.errText}>{errText(dir.error)}</div>
  return (
    <ul className={s.tree}>
      {dir.data.entries.map((e) => (
        <li key={e.path}>
          <button
            type="button"
            className={s.treeItem}
            style={{ paddingLeft: 6 + depth * 12 }}
            disabled={e.outside}
            aria-expanded={e.kind === 'dir' ? !!open[e.path] : undefined}
            onClick={() => (e.kind === 'dir' ? setOpen((o) => ({ ...o, [e.path]: !o[e.path] })) : onOpen(e.path))}
          >
            <span aria-hidden="true" className={s.treeGlyph}>
              {e.kind === 'dir' ? (open[e.path] ? '▾' : '▸') : ''}
            </span>
            <span className={s.treeName}>{e.name}</span>
            {e.git && <span className={s.treeMark} data-git={e.git}>{e.git === '수정' ? 'M' : e.git === '새 파일' ? 'U' : e.git === 'gitignore' ? '' : e.git}</span>}
          </button>
          {e.kind === 'dir' && open[e.path] && <Folder project={project} tree={tree} path={e.path} depth={depth + 1} onOpen={onOpen} />}
        </li>
      ))}
    </ul>
  )
}

/* ── 검색 ──────────────────────────────────────────────────── */

export function SearchPanel({ project, tree, onOpen }: { project: string; tree: string; onOpen: (path: string, line?: number) => void }) {
  const [text, setText] = useState('')
  const [term, setTerm] = useState('')
  const [caseOn, setCase] = useState(false)
  const got = useQuery(searchQuery(project, tree, term, caseOn))
  const groups = new Map<string, { line: number; text: string }[]>()
  for (const h of got.data?.results ?? []) groups.set(h.path, [...(groups.get(h.path) ?? []), h])
  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>프로젝트에서 검색</span>
      </div>
      <form
        className={s.row}
        onSubmit={(e) => {
          e.preventDefault()
          setTerm(text)
        }}
      >
        <input className={s.input} value={text} onChange={(e) => setText(e.target.value)} placeholder="찾을 내용 (Enter)" aria-label="찾을 내용" />
        <button type="button" className={s.toggle} aria-pressed={caseOn} title="대소문자 구분" onClick={() => setCase(!caseOn)}>
          Aa
        </button>
      </form>
      <div className={s.muted}>파일 내용을 검색해요 · {got.data?.via ?? 'git grep'} · 두 글자 이상</div>
      {got.isFetching && <div className={s.muted}>검색하는 중이에요…</div>}
      {got.data && got.data.results.length === 0 && <div className={s.muted}>검색 결과가 없어요.</div>}
      {[...groups.entries()].map(([path, hits]) => (
        <div key={path} className={s.hitGroup}>
          <button type="button" className={s.hitFile} onClick={() => onOpen(path)}>
            {path} <span className={s.muted}>{hits.length}</span>
          </button>
          {hits.slice(0, 20).map((h) => (
            <button key={h.line} type="button" className={s.hit} onClick={() => onOpen(path, h.line)}>
              <span className={s.hitLine}>{h.line}</span>
              <span className={s.hitText}>{h.text}</span>
            </button>
          ))}
        </div>
      ))}
      {got.data?.truncated && <div className={s.muted}>결과가 많아 처음 500개만 표시해요.</div>}
    </div>
  )
}

/* ── 소스 제어 ──────────────────────────────────────────────── */

export function GitPanel({ project, tree, onDiff }: { project: string; tree: string; onDiff: (path: string) => void }) {
  const status = useQuery(gitStatusQuery(project, tree))
  const caps = useQuery(gitCapsQuery(project))
  const { commit, merge, pr } = useGitAction(project)
  const [message, setMessage] = useState('')
  const [asking, setAsking] = useState(false)
  const [prOpen, setPrOpen] = useState(false)
  const [prTitle, setPrTitle] = useState('')
  const [prBody, setPrBody] = useState('')
  const st = status.data
  if (!st) return <div className={s.panel}><span className={s.muted}>불러오는 중이에요…</span></div>
  if (st.state !== 'ok') return <div className={s.panel}><span className={s.muted}>{st.state === 'none' ? 'git 저장소가 아니에요.' : st.reason}</span></div>
  const doCommit = () => commit.mutate({ tree, message }, { onSuccess: () => setMessage('') })
  const isMain = st.branch === 'main' || st.branch === 'master'

  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>소스 제어</span>
      </div>
      <div className={s.muted}>
        {st.branch || '(분리된 HEAD)'} · 커밋하지 않은 변경 {st.changed}
      </div>
      <textarea
        className={s.textarea}
        rows={2}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doCommit()
        }}
        placeholder={`메시지 (Ctrl+Enter로 ${st.branch} 브랜치에 커밋)`}
        aria-label="커밋 메시지"
      />
      <div className={s.row}>
        <button type="button" className={s.primaryBtn} disabled={!message.trim() || !st.changed || commit.isPending} onClick={doCommit}>
          ✓ 커밋
        </button>
        {caps.data?.pr && !isMain && (
          <button
            type="button"
            className={s.ghostBtn}
            title="gh로 PR을 만들어요. 브랜치를 먼저 원격 저장소에 push해야 해요"
            onClick={() => {
              setPrTitle(st.branch.replace(/^[^/]*\//, '').replace(/[-_]/g, ' '))
              setPrBody('')
              pr.reset()
              setPrOpen(true)
            }}
          >
            PR 만들기
          </button>
        )}
        {!isMain && (
          <button type="button" className={s.ghostBtn} onClick={() => setAsking(true)}>
            main에 머지…
          </button>
        )}
      </div>
      {commit.isError && <div className={s.errText}>{errText(commit.error)}</div>}
      {commit.data && <div className={s.okText}>커밋했어요 · {commit.data.sha}</div>}
      {merge.data && <div className={s.okText}>{merge.data.main} 브랜치에 머지했어요 · {merge.data.sha}</div>}
      {pr.data && (
        <div className={s.okText}>
          PR을 만들었어요 ·{' '}
          <a href={pr.data.url} target="_blank" rel="noreferrer">
            {pr.data.number ? `#${pr.data.number}` : pr.data.url}
          </a>
        </div>
      )}
      <span className={s.groupLabel}>변경 내용 · {st.changed}</span>
      {st.changes.map((c) => (
        <button key={c.path} type="button" className={s.fileRow} onClick={() => onDiff(c.path)}>
          <span className={s.mono}>{c.path}</span>
          <span className={s.treeMark} data-git={c.label}>
            {c.label}
          </span>
        </button>
      ))}
      <Dialog
        open={prOpen}
        title={`${st.branch} 브랜치로 PR 만들기`}
        confirmLabel="PR 만들기"
        busy={pr.isPending}
        error={errText(pr.error) || undefined}
        onClose={() => {
          pr.reset()
          setPrOpen(false)
        }}
        onConfirm={() => pr.mutate({ tree, title: prTitle, body: prBody }, { onSuccess: () => setPrOpen(false) })}
      >
        <label className={s.dialogField}>
          제목
          <input className={s.input} value={prTitle} onChange={(e) => setPrTitle(e.target.value)} autoFocus />
        </label>
        <label className={s.dialogField}>
          설명 (선택)
          <textarea className={s.textarea} rows={4} value={prBody} onChange={(e) => setPrBody(e.target.value)} />
        </label>
        <span>
          <code>gh pr create</code>로 만들어요. lab.remote는 push하지 않으니 브랜치를 먼저 원격 저장소에 push해 주세요 (
          <code>git push -u origin {st.branch}</code>).
        </span>
      </Dialog>
      <Dialog
        open={asking}
        title={`${st.branch} 브랜치를 main에 머지할까요?`}
        confirmLabel="머지"
        busy={merge.isPending}
        error={errText(merge.error) || undefined}
        onClose={() => {
          merge.reset()
          setAsking(false)
        }}
        onConfirm={() => merge.mutate(st.branch, { onSuccess: () => setAsking(false) })}
      >
        <span>
          main worktree에서 <code>git merge --no-ff {st.branch}</code> 명령을 실행해요. main 쪽에 커밋하지 않은 변경이 있으면 머지하지 않고, 충돌이 나면
          머지를 바로 취소해요. push는 하지 않아요.
        </span>
      </Dialog>
    </div>
  )
}

/* ── 실행 ──────────────────────────────────────────────────── */

export function RunPanel({
  project,
  detail,
  tree,
  branch,
  onAttach,
  fill,
}: {
  project: string
  detail: ProjectDetail
  tree: string
  branch: string
  onAttach: (runId: string) => void
  /** Scenario의 "실행 탭에 채우기" — 명령만 채우고 실행은 사람이 눌러요 */
  fill?: string
}) {
  const runs = useQuery(runsQuery(project))
  const start = useStartRun(project)
  const stop = useStopRun()
  const [command, setCommand] = useState(fill ?? detail.settings.commands[0] ?? '')
  const [env, setEnv] = useState(detail.settings.condaEnv)
  const [scheduling, setScheduling] = useState(false)
  const shown = env.trim() ? `conda run -s -n ${env.trim()} bash -c '${command}'` : `bash -c '${command}'`
  const all = runs.data?.runs ?? []
  const running = all.filter((r) => r.state === 'running')
  const recent = all.filter((r) => r.state !== 'running').slice(0, 8)

  return (
    <div className={s.panel}>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>실행</span>
      </div>
      <div className={s.muted}>명령 한 줄을 실행해요 · 브라우저를 닫아도 계속 실행돼요</div>
      <label className={s.field}>
        명령
        <input className={s.input} list="ide-commands" value={command} onChange={(e) => setCommand(e.target.value)} placeholder="python src/train.py" />
        <datalist id="ide-commands">
          {detail.settings.commands.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </label>
      <div className={s.kv}>
        <span>위치</span>
        <span className={s.mono}>{branch || tree || '프로젝트 루트'}</span>
      </div>
      <label className={s.field}>
        conda 환경 (비워 두면 conda 없이 실행)
        <input className={s.input} value={env} onChange={(e) => setEnv(e.target.value)} />
      </label>
      <details className={s.details}>
        <summary>실제 실행 명령 보기</summary>
        <pre className={s.code}>{shown}</pre>
        <span className={s.muted}>tmux 안에서 실행되고 로그와 종료 코드는 .labremote/runs/에 저장돼요. 지표 파일은 설정에 입력한 규칙으로 찾아요.</span>
      </details>
      <div className={s.row}>
        <button
          type="button"
          className={s.primaryBtn}
          disabled={!command.trim() || start.isPending}
          onClick={() => start.mutate({ command, env: env.trim(), cwd: tree, name: '' })}
        >
          지금 실행
        </button>
        <button type="button" className={s.ghostBtn} disabled={!command.trim()} onClick={() => setScheduling(true)}>
          예약 실행…
        </button>
      </div>
      {start.isError && <div className={s.errText}>{errText(start.error)}</div>}
      <ScheduleDialog
        key={scheduling ? 'open' : 'closed'}
        open={scheduling}
        onClose={() => setScheduling(false)}
        seed={{ kind: 'command', project, tree, command, env: env.trim() }}
      />

      <span className={s.groupLabel}>실행 중 · {running.length}</span>
      {running.map((r) => (
        <div key={r.id} className={s.runRow}>
          <span className={s.mono}>{r.name ? `${r.id} · ${r.name}` : r.id}</span>
          <span className={s.muted}>{duration(r.durationSec)}</span>
          <span className={s.spacer} />
          <button type="button" className={s.linkBtn} onClick={() => onAttach(r.id)}>
            터미널에서 열기
          </button>
          <button type="button" className={s.linkBtn} disabled={stop.isPending} onClick={() => stop.mutate({ project, id: r.id, force: false })}>
            중지
          </button>
        </div>
      ))}
      <span className={s.groupLabel}>최근 실행</span>
      {recent.map((r) => (
        <div key={r.id} className={s.runRow}>
          <span className={s.mono}>{r.name || r.id}</span>
          <RunStatePill run={r} />
          <span className={s.muted}>{whenShort(r.endedAt ?? r.startedAt)}</span>
        </div>
      ))}
    </div>
  )
}
