import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  dirQuery,
  downloadHref,
  useDeleteEntry,
  useMakeEntry,
  useMoveEntry,
  useUpload,
} from '@/api/projects'
import type { FileEntry, ProjectDetail, WorktreeList } from '@/api/projects'
import { apiUrl, ApiError } from '@/api/client'
import { Dialog, dialogStyles as ds, ErrorState, LoadingState } from '@/components'
import { useOutsideClick } from '@/lib/useOutsideClick'
import { bytes, whenShort } from '@/lib/time'
import s from './Projects.module.css'

type Ask =
  | { kind: 'make'; what: 'file' | 'dir' }
  | { kind: 'rename'; entry: FileEntry }
  | { kind: 'delete'; entry: FileEntry }
  | null

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : undefined)

export function FilesTab({ project, trees }: { project: ProjectDetail; trees?: WorktreeList }) {
  const [params, setParams] = useSearchParams()
  const tree = params.get('tree') ?? ''
  const path = params.get('path') ?? ''
  const [find, setFind] = useState('')
  const [ask, setAsk] = useState<Ask>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const listing = useQuery(dirQuery(project.name, tree, path))
  const upload = useUpload(project.name)

  const go = (next: { tree?: string; path?: string }) => {
    const sp = new URLSearchParams(params)
    sp.set('tab', 'files')
    const t = next.tree ?? tree
    const pth = next.path ?? path
    if (t) sp.set('tree', t)
    else sp.delete('tree')
    if (pth) sp.set('path', pth)
    else sp.delete('path')
    setParams(sp)
    setFind('')
  }

  // worktree 칩 — 프로젝트 안에 있는 것만 파일 표로 열 수 있어요
  const chips =
    trees?.state === 'ok'
      ? trees.worktrees.filter((w) => w.rel !== null).map((w) => ({ rel: w.rel === '.' ? '' : (w.rel ?? ''), label: w.branch || w.head }))
      : [{ rel: '', label: project.git.state === 'ok' ? project.git.branch || '(git)' : '(git 아님)' }]
  const treeLabel = chips.find((c) => c.rel === tree)?.label ?? tree

  const crumbs = path ? path.split('/') : []
  const entries = (listing.data?.entries ?? []).filter((e) => !find || e.name.toLowerCase().includes(find.toLowerCase()))

  return (
    <>
      <div className={s.toolbar}>
        <span className={s.toolLabel}>worktree</span>
        <div role="group" aria-label="worktree 고르기" className={s.treeChips}>
          {chips.map((c) => (
            <button key={c.rel || '.'} type="button" aria-pressed={c.rel === tree} onClick={() => go({ tree: c.rel, path: '' })} className={s.treeChip}>
              {c.label}
            </button>
          ))}
        </div>
        <label htmlFor="pj-find" className={s.srOnly}>
          파일 검색
        </label>
        <input
          id="pj-find"
          type="text"
          placeholder="이 폴더에서 이름 검색"
          value={find}
          onChange={(e) => setFind(e.target.value)}
          className={s.find}
        />
        <button type="button" className={s.toolBtn} onClick={() => setAsk({ kind: 'make', what: 'dir' })}>
          새 폴더
        </button>
        <button type="button" className={s.toolBtn} onClick={() => setAsk({ kind: 'make', what: 'file' })}>
          새 파일
        </button>
        <button type="button" className={s.toolBtn} onClick={() => uploadRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? '올리는 중…' : '업로드'}
        </button>
        <input
          ref={uploadRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            e.target.value = ''
            if (files.length) upload.mutate({ tree, dir: path, files })
          }}
        />
      </div>
      {upload.isError && (
        <div role="alert" className={s.notice}>
          올리지 못했어요: {errText(upload.error)}
        </div>
      )}

      <nav aria-label="경로" className={s.crumbs}>
        <button type="button" className={s.crumb} onClick={() => go({ path: '' })}>
          {project.path}
        </button>
        {' / '}
        <b className={s.crumbTree}>{treeLabel}</b>
        {crumbs.map((c, i) => (
          <span key={i}>
            {' / '}
            <button type="button" className={s.crumb} onClick={() => go({ path: crumbs.slice(0, i + 1).join('/') })}>
              {c}
            </button>
          </span>
        ))}
      </nav>

      <div className={s.tableWrap}>
        {listing.isPending && <LoadingState label="파일을 불러오는 중이에요" />}
        {listing.isError && <ErrorState error={listing.error} onRetry={() => listing.refetch()} />}
        {listing.isSuccess && (
          <table className={s.table}>
            <thead>
              <tr>
                <th className={s.thFirst}>이름</th>
                <th>git</th>
                <th className={s.right}>크기</th>
                <th>수정</th>
                <th className={s.thLast}>동작</th>
              </tr>
            </thead>
            <tbody>
              {path && (
                <tr>
                  <td className={s.tdFirst} colSpan={5}>
                    <button type="button" className={s.nameBtn} onClick={() => go({ path: crumbs.slice(0, -1).join('/') })}>
                      <span aria-hidden="true" className={s.glyph}>
                        ‹
                      </span>
                      <span className={s.fileName}>..</span>
                    </button>
                  </td>
                </tr>
              )}
              {entries.map((e) => (
                <FileRow key={e.path} e={e} project={project} tree={tree} onOpenDir={() => go({ path: e.path })} onAsk={setAsk} />
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan={5} className={s.emptyRow}>
                    {find ? '맞는 파일이 없어요.' : '빈 폴더예요.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
        {listing.data?.truncated && <div className={s.muted}>항목이 많아 앞의 2000개만 보여요.</div>}
      </div>
      <div className={s.note}>
        이름 바꾸기 · 이동 · 삭제는 ··· 에 있어요. 삭제는 한 번 더 확인하고, 실행 중인 학습이 쓰는 폴더는 지울 수 없어요.
      </div>

      <FileDialogs project={project.name} tree={tree} dir={path} ask={ask} onClose={() => setAsk(null)} />
    </>
  )
}

function FileRow({
  e,
  project,
  tree,
  onOpenDir,
  onAsk,
}: {
  e: FileEntry
  project: ProjectDetail
  tree: string
  onOpenDir: () => void
  onAsk: (a: Ask) => void
}) {
  const isDir = e.kind === 'dir'
  const ide = `/projects/${encodeURIComponent(project.name)}/ide?${new URLSearchParams({ ...(tree ? { tree } : {}), path: e.path })}`
  return (
    <tr>
      <td className={s.tdFirst}>
        {isDir && !e.outside ? (
          <button type="button" className={s.nameBtn} onClick={onOpenDir}>
            <span aria-hidden="true" className={s.glyph} data-dir="true">
              ▸
            </span>
            <span className={s.fileName}>{e.name}/</span>
          </button>
        ) : (
          <span className={s.nameBtn}>
            <span aria-hidden="true" className={s.glyph}>
              ·
            </span>
            <span className={s.fileName}>{e.name}</span>
            {e.link && <span className={s.linkTag}>{e.outside ? '링크 · 프로젝트 밖' : '링크'}</span>}
          </span>
        )}
      </td>
      <td>
        <span className={s.gitTag} data-git={e.git || 'none'}>
          {e.git || '—'}
        </span>
      </td>
      <td className={`${s.right} ${s.monoCell}`}>{isDir ? '—' : bytes(e.size)}</td>
      <td className={s.when}>{whenShort(e.mtime)}</td>
      <td className={s.actions}>
        {!isDir && !e.outside && (
          <>
            <Link to={ide} className={s.actLink}>
              열기
            </Link>
            <a href={apiUrl(downloadHref(project.name, tree, e.path))} className={s.actBtn} download>
              내려받기
            </a>
          </>
        )}
        <MoreMenu e={e} onAsk={onAsk} />
      </td>
    </tr>
  )
}

function MoreMenu({ e, onAsk }: { e: FileEntry; onAsk: (a: Ask) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useOutsideClick(ref, () => setOpen(false), open)
  return (
    <span ref={ref} className={s.moreWrap}>
      <button
        type="button"
        aria-label={`${e.name} 더보기`}
        aria-haspopup="menu"
        aria-expanded={open}
        className={s.more}
        onClick={() => setOpen((v) => !v)}
      >
        ···
      </button>
      {open && (
        <span role="menu" className={s.moreMenu}>
          <button type="button" role="menuitem" className={s.moreItem} onClick={() => (setOpen(false), onAsk({ kind: 'rename', entry: e }))}>
            이름 바꾸기 · 이동
          </button>
          <button
            type="button"
            role="menuitem"
            className={s.moreItem}
            data-tone="danger"
            onClick={() => (setOpen(false), onAsk({ kind: 'delete', entry: e }))}
          >
            삭제…
          </button>
        </span>
      )}
    </span>
  )
}

function FileDialogs({ project, tree, dir, ask, onClose }: { project: string; tree: string; dir: string; ask: Ask; onClose: () => void }) {
  const make = useMakeEntry(project)
  const move = useMoveEntry(project)
  const del = useDeleteEntry(project)
  const [value, setValue] = useState('')
  const { reset: resetMake } = make
  const { reset: resetMove } = move
  const { reset: resetDel } = del

  // 새 창이 열릴 때 입력칸을 채우고 지난 오류를 지워요
  useEffect(() => {
    setValue(ask?.kind === 'rename' ? ask.entry.path : '')
    resetMake()
    resetMove()
    resetDel()
  }, [ask, resetMake, resetMove, resetDel])
  const join = (name: string) => (dir ? `${dir}/${name}` : name)

  return (
    <>
      <Dialog
        open={ask?.kind === 'make'}
        title={ask?.kind === 'make' && ask.what === 'dir' ? '새 폴더' : '새 파일'}
        confirmLabel="만들기"
        busy={make.isPending}
        error={errText(make.error)}
        onClose={onClose}
        onConfirm={() =>
          ask?.kind === 'make' && make.mutate({ tree, path: join(value.trim()), kind: ask.what }, { onSuccess: onClose })
        }
      >
        <label className={ds.field}>
          이름
          <input className={ds.input} value={value} onChange={(e) => setValue(e.target.value)} autoFocus required />
        </label>
      </Dialog>

      <Dialog
        open={ask?.kind === 'rename'}
        title="이름 바꾸기 · 이동"
        confirmLabel="바꾸기"
        busy={move.isPending}
        error={errText(move.error)}
        onClose={onClose}
        onConfirm={() =>
          ask?.kind === 'rename' && move.mutate({ tree, from: ask.entry.path, to: value.trim() }, { onSuccess: onClose })
        }
      >
        <label className={ds.field}>
          새 경로 (이 worktree 안 상대 경로)
          <input className={ds.input} value={value} onChange={(e) => setValue(e.target.value)} autoFocus required />
        </label>
        <span>같은 이름이 이미 있으면 덮어쓰지 않고 멈춰요.</span>
      </Dialog>

      <Dialog
        open={ask?.kind === 'delete'}
        title="삭제할까요?"
        confirmLabel="삭제"
        tone="danger"
        busy={del.isPending}
        error={errText(del.error)}
        onClose={onClose}
        onConfirm={() =>
          ask?.kind === 'delete' &&
          del.mutate({ tree, path: ask.entry.path, confirm: ask.entry.name }, { onSuccess: onClose })
        }
      >
        {ask?.kind === 'delete' && (
          <span>
            <b className={s.mono}>{ask.entry.path}</b>
            {ask.entry.kind === 'dir' && !ask.entry.link ? ' 폴더와 그 안의 모든 파일' : ''}을 지워요. 되돌릴 수 없어요.
            {ask.entry.link && ' 링크만 지우고 링크가 가리키는 곳은 그대로 둬요.'}
          </span>
        )}
      </Dialog>
    </>
  )
}
