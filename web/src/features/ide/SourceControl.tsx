import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { gitStatusQuery } from '@/api/projects'
import { gitCapsQuery, repoInfoQuery, useGitAction, useRepoAction } from '@/api/ide'
import type { RepoInfo } from '@/api/ide'
import { ApiError } from '@/api/client'
import { Dialog } from '@/components'
import { RefreshIcon } from '@/components/icons'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './Ide.module.css'

/*
 * 소스 제어 — VS Code와 같은 구조예요.
 *   리포지토리: 저장소 이름 · 브랜치(누르면 전환/만들기) · 동기화(↓ ↑) · PR · 더보기
 *   변경 내용: 커밋 메시지 · 커밋(+ 커밋 후 Push/동기화) · 스테이징된 변경 내용 · 변경 내용
 * 원격 전송(fetch · pull · push)은 누를 때만 하고, push 전에는 원격 주소를 보여 주고 확인을 받아요.
 */

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : '')

/* ── 아이콘 (VS Code 소스 제어와 같은 모양) ───────────────────── */

function Ico({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}
const RepoIcon = () => (
  <Ico>
    <path d="M6 3h11a1 1 0 011 1v13H7a2 2 0 00-2 2V5a2 2 0 011-2z" />
    <path d="M5 19a2 2 0 002 2h11v-4" />
  </Ico>
)
const BranchIcon = () => (
  <Ico>
    <circle cx="6" cy="5" r="2" />
    <circle cx="6" cy="19" r="2" />
    <circle cx="18" cy="7" r="2" />
    <path d="M6 7v10M18 9c0 5-6 4-11.5 8.5" />
  </Ico>
)
const SyncIcon = () => (
  <Ico>
    <path d="M20 11a8 8 0 00-14.3-4.4L4 8" />
    <path d="M4 4v4h4" />
    <path d="M4 13a8 8 0 0014.3 4.4L20 16" />
    <path d="M20 20v-4h-4" />
  </Ico>
)
const CloudIcon = () => (
  <Ico>
    <path d="M7 18a4.5 4.5 0 01-.6-9 6 6 0 0111.6 1.5A3.8 3.8 0 0117.5 18" />
    <path d="M12 12v8M9 15l3-3 3 3" />
  </Ico>
)
const CheckIcon = () => (
  <Ico>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Ico>
)
const PrIcon = () => (
  <Ico>
    <circle cx="6" cy="5" r="2" />
    <circle cx="6" cy="19" r="2" />
    <circle cx="18" cy="19" r="2" />
    <path d="M6 7v10M18 17V9a3 3 0 00-3-3h-4M13 3.5L10.5 6 13 8.5" />
  </Ico>
)
const MoreIcon = () => (
  <Ico>
    <circle cx="5" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="19" cy="12" r="1" fill="currentColor" />
  </Ico>
)
const PlusIcon = () => (
  <Ico>
    <path d="M12 5v14M5 12h14" />
  </Ico>
)
const MinusIcon = () => (
  <Ico>
    <path d="M5 12h14" />
  </Ico>
)
const DiscardIcon = () => (
  <Ico>
    <path d="M9 14L4 9l5-5" />
    <path d="M4 9h10a6 6 0 010 12h-3" />
  </Ico>
)
const Chevron = ({ open }: { open: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true" style={{ transform: open ? undefined : 'rotate(-90deg)' }}>
    <path d="M6 9l6 6 6-6" />
  </svg>
)

/* ── 작은 부품 ─────────────────────────────────────────────── */

function IconBtn({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button type="button" className={s.iconBtnSm} aria-label={label} title={label} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

interface MenuItem {
  label: string
  onSelect: () => void
  disabled?: boolean
}

function Menu({ label, items, icon }: { label: string; items: (MenuItem | '-')[]; icon?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLSpanElement>(null)
  useOutsideClick(wrap, () => setOpen(false), open)
  return (
    <span ref={wrap} className={s.menuWrap}>
      <button type="button" className={s.iconBtnSm} aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {icon ?? <MoreIcon />}
      </button>
      {open && (
        <div role="menu" className={s.menu}>
          {items.map((it, i) =>
            it === '-' ? (
              <div key={`sep${i}`} className={s.menuSep} role="separator" />
            ) : (
              <button
                key={it.label}
                type="button"
                role="menuitem"
                className={s.menuItem}
                disabled={it.disabled}
                onClick={() => {
                  setOpen(false)
                  it.onSelect()
                }}
              >
                {it.label}
              </button>
            ),
          )}
        </div>
      )}
    </span>
  )
}

function Section({ title, count, open, onToggle, actions, children }: { title: string; count?: number; open: boolean; onToggle: () => void; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className={s.scSection}>
      <div className={s.scHead}>
        <button type="button" className={s.scToggle} aria-expanded={open} onClick={onToggle}>
          <Chevron open={open} />
          <span>{title}</span>
          {count !== undefined && <span className={s.scCount}>{count}</span>}
        </button>
        {actions && <span className={s.scActions}>{actions}</span>}
      </div>
      {open && children}
    </div>
  )
}

/* ── 변경 파일 나누기 (porcelain XY: X=스테이징, Y=작업 폴더) ──── */

const LETTER: Record<string, string> = { M: 'M', T: 'M', A: 'A', D: 'D', R: 'R', C: 'C', U: '!', '?': 'U' }
const LETTER_TITLE: Record<string, string> = { M: '수정됨', A: '추가됨', D: '삭제됨', R: '이름 바뀜', C: '복사됨', U: '추적되지 않음', '!': '충돌' }

interface Row {
  path: string
  letter: string
  untracked: boolean
}

function splitChanges(changes: { path: string; xy: string }[]) {
  const staged: Row[] = []
  const unstaged: Row[] = []
  for (const c of changes) {
    const [x, y] = [c.xy[0] ?? ' ', c.xy[1] ?? ' ']
    if (c.xy === 'UU' || x === 'U' || y === 'U') {
      unstaged.push({ path: c.path, letter: '!', untracked: false })
      continue
    }
    if (c.xy === '??') {
      unstaged.push({ path: c.path, letter: 'U', untracked: true })
      continue
    }
    if (x !== ' ') staged.push({ path: c.path, letter: LETTER[x] ?? 'M', untracked: false })
    if (y !== ' ') unstaged.push({ path: c.path, letter: LETTER[y] ?? 'M', untracked: false })
  }
  return { staged, unstaged }
}

function FileRow({ row, onOpen, actions }: { row: Row; onOpen: () => void; actions: ReactNode }) {
  const slash = row.path.lastIndexOf('/')
  const name = slash >= 0 ? row.path.slice(slash + 1) : row.path
  const dir = slash >= 0 ? row.path.slice(0, slash) : ''
  return (
    <div className={s.scRow}>
      <button type="button" className={s.scFile} onClick={onOpen} title={`${row.path} · 변경 내용 보기`}>
        <span className={s.scName} data-deleted={row.letter === 'D' || undefined}>
          {name}
        </span>
        {dir && <span className={s.scDir}>{dir}</span>}
      </button>
      <span className={s.scRowActions}>{actions}</span>
      <span className={s.scLetter} data-l={row.letter} title={LETTER_TITLE[row.letter]}>
        {row.letter}
      </span>
    </div>
  )
}

/* ── 패널 ──────────────────────────────────────────────────── */

type Dlg =
  | null
  | { kind: 'branch' }
  | { kind: 'push' }
  | { kind: 'sync' }
  | { kind: 'remote' }
  | { kind: 'publish' }
  | { kind: 'merge' }
  | { kind: 'pr' }
  | { kind: 'discard'; path: string; untracked: boolean }

type Ok = Extract<RepoInfo, { state: 'ok' }>

export function GitPanel({ project, tree, onDiff }: { project: string; tree: string; onDiff: (path: string) => void }) {
  const qc = useQueryClient()
  const status = useQuery(gitStatusQuery(project, tree))
  const repo = useQuery(repoInfoQuery(project, tree))
  const caps = useQuery(gitCapsQuery(project))
  const git = useGitAction(project)
  const act = useRepoAction(project, tree)
  const [open, setOpen] = useState({ repo: true, changes: true, staged: true, unstaged: true })
  const [message, setMessage] = useState('')
  const [dialog, setDialog] = useState<Dlg>(null)
  const [dlgErr, setDlgErr] = useState('')
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [working, setWorking] = useState('')
  // 대화 상자 입력
  const [query, setQuery] = useState('')
  const [remoteUrl, setRemoteUrl] = useState('')
  const [pubName, setPubName] = useState('')
  const [pubPrivate, setPubPrivate] = useState(true)
  const [prTitle, setPrTitle] = useState('')
  const [prBody, setPrBody] = useState('')

  const refresh = () => {
    setNote(null)
    qc.invalidateQueries({ queryKey: ['projects', project, 'git'] })
    qc.invalidateQueries({ queryKey: ['projects', project, 'files'] })
  }

  /** 대화 상자 없이 바로 하는 작업 — 결과는 패널 위 한 줄로 */
  const exec = async (doing: string, fn: () => Promise<unknown>, ok: string) => {
    setNote(null)
    setWorking(doing)
    try {
      await fn()
      setNote({ ok: true, text: ok })
    } catch (e) {
      setNote({ ok: false, text: errText(e) })
    } finally {
      setWorking('')
    }
  }

  /** 대화 상자의 확인 — 실패하면 창 안에 오류를 보여 줘요 */
  const confirm = async (fn: () => Promise<unknown>, ok: string) => {
    setDlgErr('')
    try {
      const got = await fn()
      setDialog(null)
      setNote({ ok: true, text: typeof got === 'string' ? got : ok })
    } catch (e) {
      setDlgErr(errText(e))
    }
  }

  const openDialog = (d: Exclude<Dlg, null>) => {
    setDlgErr('')
    setQuery('')
    setDialog(d)
  }

  const r = repo.data
  const head = (
    <div className={s.panelHead}>
      <span className={s.panelTitle}>소스 제어</span>
      <IconBtn label="새로 고침" onClick={refresh}>
        <RefreshIcon />
      </IconBtn>
    </div>
  )

  if (!r || !status.data) return <div className={s.panel}>{head}<span className={s.muted}>불러오는 중이에요…</span></div>

  if (r.state === 'none') {
    return (
      <div className={s.panel}>
        {head}
        <p className={s.scHint}>이 폴더는 아직 git 저장소가 아니에요. 저장소를 초기화하면 변경 내용을 추적하고 커밋할 수 있어요.</p>
        <button
          type="button"
          className={s.scWide}
          disabled={act.init.isPending}
          onClick={() => exec('초기화하는 중이에요…', () => act.init.mutateAsync(), '저장소를 초기화했어요. 첫 커밋을 만든 뒤 GitHub에 게시할 수 있어요.')}
        >
          리포지토리 초기화
        </button>
        {note && <div className={note.ok ? s.okText : s.errText}>{note.text}</div>}
      </div>
    )
  }
  if (r.state !== 'ok' || status.data.state !== 'ok') {
    const reason = r.state !== 'ok' ? r.reason : status.data.state !== 'ok' ? status.data.reason : ''
    return (
      <div className={s.panel}>
        {head}
        <p className={s.errText} style={{ whiteSpace: 'pre-wrap' }}>
          {reason || 'git을 사용할 수 없어요.'}
        </p>
      </div>
    )
  }

  const st = status.data
  const branch = r.branch
  const isMain = branch === 'main' || branch === 'master'
  const hasRemote = r.remotes.length > 0
  const { staged, unstaged } = splitChanges(st.changes)
  const busy = !!working || Object.values(act).some((m) => m.isPending) || git.commit.isPending
  const target = pushTarget(r)

  const doCommit = async (then?: 'push' | 'sync') => {
    if (!message.trim()) return
    setNote(null)
    try {
      const got = await git.commit.mutateAsync({ tree, message })
      setMessage('')
      setNote({ ok: true, text: `커밋했어요 · ${got.sha}` })
      if (then) openDialog({ kind: then })
    } catch (e) {
      setNote({ ok: false, text: errText(e) })
    }
  }

  const repoMenu: (MenuItem | '-')[] = [
    ...(hasRemote
      ? [
          { label: 'Pull', onSelect: () => exec('pull하는 중이에요…', () => act.pull.mutateAsync(), 'pull했어요.'), disabled: !r.upstream },
          { label: 'Push…', onSelect: () => openDialog({ kind: 'push' }), disabled: !r.hasCommit || !branch },
          { label: '동기화…', onSelect: () => openDialog({ kind: 'sync' }), disabled: !r.upstream },
          { label: 'Fetch', onSelect: () => exec('fetch하는 중이에요…', () => act.fetch.mutateAsync(), '원격의 최신 상태를 가져왔어요.') },
          '-' as const,
        ]
      : []),
    { label: '브랜치 전환/만들기…', onSelect: () => openDialog({ kind: 'branch' }) },
    ...(!isMain && branch && r.hasCommit ? [{ label: 'main에 머지…', onSelect: () => openDialog({ kind: 'merge' }) }] : []),
    '-',
    {
      label: hasRemote ? '원격 저장소 주소 변경…' : '원격 저장소 연결…',
      onSelect: () => {
        setRemoteUrl(r.remotes.find((x) => x.name === 'origin')?.url ?? '')
        openDialog({ kind: 'remote' })
      },
    },
    ...(!hasRemote && r.gh
      ? [
          {
            label: 'GitHub에 게시…',
            onSelect: () => {
              setPubName(r.repo)
              setPubPrivate(true)
              openDialog({ kind: 'publish' })
            },
          },
        ]
      : []),
  ]

  const changeMenu: (MenuItem | '-')[] = [
    { label: '모두 스테이징', disabled: !unstaged.length, onSelect: () => exec('', () => act.stage.mutateAsync({ paths: unstaged.map((x) => x.path) }), '모든 변경 내용을 스테이징했어요.') },
    { label: '모두 스테이징 취소', disabled: !staged.length, onSelect: () => exec('', () => act.unstage.mutateAsync({ paths: staged.map((x) => x.path) }), '스테이징을 모두 취소했어요.') },
    '-',
    { label: '커밋 후 Push', disabled: !message.trim() || !st.changed || !hasRemote, onSelect: () => doCommit('push') },
    { label: '커밋 후 동기화', disabled: !message.trim() || !st.changed || !r.upstream, onSelect: () => doCommit('sync') },
  ]

  const openPr = () => {
    setPrTitle(branch.replace(/^[^/]*\//, '').replace(/[-_]/g, ' '))
    setPrBody('')
    openDialog({ kind: 'pr' })
  }

  return (
    <div className={s.panel}>
      {head}
      {working && <div className={s.muted}>{working}</div>}
      {note && <div className={note.ok ? s.okText : s.errText}>{note.text}</div>}

      <Section title="리포지토리" open={open.repo} onToggle={() => setOpen((o) => ({ ...o, repo: !o.repo }))}>
        <div className={s.repoRow}>
          <span className={s.repoIcon}>
            <RepoIcon />
          </span>
          <span className={s.repoName} title={r.remotes[0]?.url || r.repo}>
            {r.repo}
          </span>
          <button type="button" className={s.branchBtn} title="브랜치 전환/만들기" onClick={() => openDialog({ kind: 'branch' })}>
            <BranchIcon />
            <span>{branch || `(분리된 HEAD ${r.head})`}</span>
          </button>
          {r.upstream ? (
            <button type="button" className={s.syncBtn} title={`변경 내용 동기화 · 받을 커밋 ${r.behind}개, 보낼 커밋 ${r.ahead}개`} onClick={() => openDialog({ kind: 'sync' })} disabled={busy}>
              <SyncIcon />
              {(r.behind > 0 || r.ahead > 0) && (
                <span>
                  {r.behind}↓ {r.ahead}↑
                </span>
              )}
            </button>
          ) : (
            hasRemote &&
            r.hasCommit &&
            branch && (
              <IconBtn label="브랜치 게시" onClick={() => openDialog({ kind: 'push' })} disabled={busy}>
                <CloudIcon />
              </IconBtn>
            )
          )}
          {caps.data?.pr && hasRemote && branch && !isMain && (
            <IconBtn label="PR 만들기" onClick={openPr} disabled={busy}>
              <PrIcon />
            </IconBtn>
          )}
          <Menu label="리포지토리 작업 더보기" items={repoMenu} />
        </div>
        {!hasRemote && (
          <p className={s.scHint}>
            연결된 원격 저장소가 없어요.{' '}
            <button
              type="button"
              className={s.linkBtn}
              onClick={() => {
                setRemoteUrl('')
                openDialog({ kind: 'remote' })
              }}
            >
              원격 저장소 연결
            </button>
            {r.gh && (
              <>
                {' · '}
                <button
                  type="button"
                  className={s.linkBtn}
                  onClick={() => {
                    setPubName(r.repo)
                    setPubPrivate(true)
                    openDialog({ kind: 'publish' })
                  }}
                >
                  GitHub에 게시
                </button>
              </>
            )}
          </p>
        )}
      </Section>

      <Section
        title="변경 내용"
        open={open.changes}
        onToggle={() => setOpen((o) => ({ ...o, changes: !o.changes }))}
        actions={
          <>
            <IconBtn label="커밋" onClick={() => doCommit()} disabled={!message.trim() || !st.changed || busy}>
              <CheckIcon />
            </IconBtn>
            <IconBtn label="새로 고침" onClick={refresh}>
              <RefreshIcon size={16} />
            </IconBtn>
            <Menu label="변경 내용 작업 더보기" items={changeMenu} />
          </>
        }
      >
        <textarea
          className={s.textarea}
          rows={2}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault()
              doCommit()
            }
          }}
          placeholder={branch ? `메시지 (Ctrl+Enter로 '${branch}' 브랜치에 커밋)` : '메시지 (Ctrl+Enter로 커밋)'}
          aria-label="커밋 메시지"
        />
        <div className={s.commitSplit}>
          <button type="button" className={s.commitMain} disabled={!message.trim() || !st.changed || busy} onClick={() => doCommit()}>
            <CheckIcon /> 커밋
          </button>
          <Menu label="커밋 방법 선택" icon={<Chevron open />} items={changeMenu.slice(3)} />
        </div>
        {staged.length > 0 && (
          <Section
            title="스테이징된 변경 내용"
            count={staged.length}
            open={open.staged}
            onToggle={() => setOpen((o) => ({ ...o, staged: !o.staged }))}
            actions={
              <IconBtn label="모두 스테이징 취소" onClick={() => exec('', () => act.unstage.mutateAsync({ paths: staged.map((x) => x.path) }), '스테이징을 모두 취소했어요.')}>
                <MinusIcon />
              </IconBtn>
            }
          >
            {staged.map((row) => (
              <FileRow
                key={`s:${row.path}`}
                row={row}
                onOpen={() => onDiff(row.path)}
                actions={
                  <IconBtn label="스테이징 취소" onClick={() => exec('', () => act.unstage.mutateAsync({ paths: [row.path] }), '')}>
                    <MinusIcon />
                  </IconBtn>
                }
              />
            ))}
          </Section>
        )}
        <Section
          title="변경 내용"
          count={unstaged.length}
          open={open.unstaged}
          onToggle={() => setOpen((o) => ({ ...o, unstaged: !o.unstaged }))}
          actions={
            unstaged.length > 0 && (
              <IconBtn label="모두 스테이징" onClick={() => exec('', () => act.stage.mutateAsync({ paths: unstaged.map((x) => x.path) }), '모든 변경 내용을 스테이징했어요.')}>
                <PlusIcon />
              </IconBtn>
            )
          }
        >
          {unstaged.length === 0 && <div className={s.muted}>{staged.length ? '스테이징하지 않은 변경 내용이 없어요.' : '커밋하지 않은 변경 내용이 없어요.'}</div>}
          {unstaged.map((row) => (
            <FileRow
              key={`u:${row.path}`}
              row={row}
              onOpen={() => onDiff(row.path)}
              actions={
                <>
                  <IconBtn label="변경 내용 취소" onClick={() => openDialog({ kind: 'discard', path: row.path, untracked: row.untracked })}>
                    <DiscardIcon />
                  </IconBtn>
                  <IconBtn label="변경 내용 스테이징" onClick={() => exec('', () => act.stage.mutateAsync({ paths: [row.path] }), '')}>
                    <PlusIcon />
                  </IconBtn>
                </>
              }
            />
          ))}
        </Section>
        {!staged.length && unstaged.length > 0 && <p className={s.scHint}>스테이징한 변경 내용이 없으면 모든 변경 내용을 커밋해요.</p>}
      </Section>

      {/* ── 대화 상자 ── */}
      <BranchDialog
        open={dialog?.kind === 'branch'}
        info={r}
        query={query}
        setQuery={setQuery}
        error={dlgErr}
        busy={act.checkout.isPending || act.branch.isPending}
        onClose={() => setDialog(null)}
        onPick={(name) => confirm(() => act.checkout.mutateAsync({ name }), `${name} 브랜치로 전환했어요.`)}
        onCreate={(name) => confirm(() => act.branch.mutateAsync({ name }), `${name} 브랜치를 만들고 전환했어요.`)}
      />

      <Dialog
        open={dialog?.kind === 'push'}
        title={r.upstream ? 'Push할까요?' : '브랜치를 게시할까요?'}
        confirmLabel={r.upstream ? 'Push' : '게시'}
        busy={act.push.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => confirm(() => act.push.mutateAsync(), r.upstream ? 'push했어요.' : `${branch} 브랜치를 게시했어요.`)}
      >
        <span>
          {r.upstream
            ? `${target.name} 원격 저장소의 ${branch} 브랜치로 커밋 ${r.ahead}개를 push해요.`
            : `${target.name} 원격 저장소에 ${branch} 브랜치를 새로 만들고 push해요.`}
        </span>
        <code className={s.scUrl}>{target.url}</code>
        <span className={s.muted}>force push는 하지 않아요. 원격에 로컬에 없는 커밋이 있으면 push하지 않고 알려 줘요.</span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'sync'}
        title="변경 내용을 동기화할까요?"
        confirmLabel="동기화"
        busy={act.sync.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => confirm(() => act.sync.mutateAsync(), '동기화했어요.')}
      >
        <span>
          {target.name} 원격 저장소에서 pull한 뒤 {branch} 브랜치의 커밋을 push해요. 마지막으로 확인했을 때 받을 커밋은 {r.behind}개, 보낼 커밋은 {r.ahead}개예요.
        </span>
        <code className={s.scUrl}>{target.url}</code>
        <span className={s.muted}>pull은 merge 방식이에요. 충돌이 나면 머지를 취소하고 알려 줘요.</span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'remote'}
        title={hasRemote ? '원격 저장소 주소 변경' : '원격 저장소 연결'}
        confirmLabel={hasRemote ? '변경' : '연결'}
        busy={act.remote.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => confirm(() => act.remote.mutateAsync({ url: remoteUrl }), hasRemote ? '원격 저장소 주소를 변경했어요.' : '원격 저장소를 연결했어요.')}
      >
        <label className={s.dialogField}>
          origin 주소
          <input className={s.input} value={remoteUrl} onChange={(e) => setRemoteUrl(e.target.value)} placeholder="https://github.com/사용자/저장소.git" autoFocus />
        </label>
        <span className={s.muted}>https:// 또는 git@github.com:사용자/저장소.git 형식이에요. 인증은 이 PC에 설정된 gh 로그인이나 SSH 키를 사용해요.</span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'publish'}
        title="GitHub에 게시"
        confirmLabel="게시"
        busy={act.publish.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => confirm(() => act.publish.mutateAsync({ name: pubName, private: pubPrivate }), 'GitHub에 게시했어요.')}
      >
        <label className={s.dialogField}>
          저장소 이름
          <input className={s.input} value={pubName} onChange={(e) => setPubName(e.target.value)} autoFocus />
        </label>
        <div className={s.radioRow} role="radiogroup" aria-label="공개 범위">
          <label>
            <input type="radio" checked={pubPrivate} onChange={() => setPubPrivate(true)} /> 비공개
          </label>
          <label>
            <input type="radio" checked={!pubPrivate} onChange={() => setPubPrivate(false)} /> 공개
          </label>
        </div>
        <span className={s.muted}>
          gh로 GitHub에 새 저장소를 만들고 origin으로 연결한 뒤 {branch || '현재'} 브랜치를 push해요.
          {!r.hasCommit && ' 아직 커밋이 없어서 먼저 커밋해야 해요.'}
        </span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'merge'}
        title={`${branch} 브랜치를 main에 머지할까요?`}
        confirmLabel="머지"
        busy={git.merge.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => confirm(async () => {
          const got = await git.merge.mutateAsync(branch)
          return `${got.main} 브랜치에 머지했어요 · ${got.sha}`
        }, 'main 브랜치에 머지했어요.')}
      >
        <span>
          main worktree에서 <code>git merge --no-ff {branch}</code> 명령을 실행해요. main 쪽에 커밋하지 않은 변경이 있으면 머지하지 않고, 충돌이 나면 머지를 바로 취소해요.
        </span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'pr'}
        title={`${branch} 브랜치로 PR 만들기`}
        confirmLabel="PR 만들기"
        busy={git.pr.isPending || act.push.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() =>
          confirm(async () => {
            if (!r.upstream || r.ahead > 0) await act.push.mutateAsync()
            const got = await git.pr.mutateAsync({ tree, title: prTitle, body: prBody })
            return `PR을 만들었어요 · ${got.number ? `#${got.number}` : got.url}`
          }, 'PR을 만들었어요.')
        }
      >
        <label className={s.dialogField}>
          제목
          <input className={s.input} value={prTitle} onChange={(e) => setPrTitle(e.target.value)} autoFocus />
        </label>
        <label className={s.dialogField}>
          설명 (선택)
          <textarea className={s.textarea} rows={4} value={prBody} onChange={(e) => setPrBody(e.target.value)} />
        </label>
        <span className={s.muted}>
          <code>gh pr create</code>로 만들어요.
          {(!r.upstream || r.ahead > 0) && ` 브랜치를 먼저 ${target.name} 원격 저장소에 push해요.`}
        </span>
      </Dialog>

      <Dialog
        open={dialog?.kind === 'discard'}
        title={dialog?.kind === 'discard' ? `${dialog.path} 파일의 변경 내용을 취소할까요?` : ''}
        confirmLabel="변경 내용 취소"
        tone="danger"
        busy={git.discard.isPending}
        error={dlgErr || undefined}
        onClose={() => setDialog(null)}
        onConfirm={() => dialog?.kind === 'discard' && confirm(() => git.discard.mutateAsync({ tree, path: dialog.path }), '변경 내용을 취소했어요.')}
      >
        <span>{dialog?.kind === 'discard' && dialog.untracked ? '새로 만든 파일이라 삭제돼요.' : '마지막 커밋 상태로 돌아가요.'} 취소한 내용은 복구할 수 없어요.</span>
      </Dialog>
    </div>
  )
}

/** push 대상 — upstream이 있으면 그 원격, 없으면 origin(없으면 첫 원격) */
function pushTarget(r: Ok) {
  const name = r.upstream ? r.upstream.split('/')[0] : r.remotes.find((x) => x.name === 'origin') ? 'origin' : r.remotes[0]?.name ?? 'origin'
  const url = r.remotes.find((x) => x.name === name)?.url ?? ''
  return { name, url }
}

/** 브랜치 전환/만들기 — VS Code의 "체크아웃할 대상" 목록처럼 */
function BranchDialog({
  open,
  info,
  query,
  setQuery,
  error,
  busy,
  onClose,
  onPick,
  onCreate,
}: {
  open: boolean
  info: Ok
  query: string
  setQuery: (v: string) => void
  error: string
  busy: boolean
  onClose: () => void
  onPick: (name: string) => void
  onCreate: (name: string) => void
}) {
  const q = query.trim().toLowerCase()
  const local = info.local.filter((b) => !q || b.name.toLowerCase().includes(q))
  const localNames = new Set(info.local.map((b) => b.name))
  const remote = info.remote.filter((b) => (!q || b.name.toLowerCase().includes(q)) && !localNames.has(b.name.split('/').slice(1).join('/')))
  const exists = localNames.has(query.trim())
  return (
    <Dialog
      open={open}
      title="브랜치 전환/만들기"
      confirmLabel={query.trim() && !exists ? `'${query.trim()}' 브랜치 만들기` : '새 브랜치 만들기'}
      busy={busy}
      error={error || undefined}
      onClose={onClose}
      onConfirm={() => {
        const name = query.trim()
        if (!name) return
        if (exists) onPick(name)
        else onCreate(name)
      }}
    >
      <input className={s.input} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="브랜치 이름 검색 또는 새 브랜치 이름" aria-label="브랜치 이름" autoFocus />
      <span className={s.muted}>브랜치를 누르면 바로 전환해요. 새 브랜치는 현재 커밋에서 만들어요.</span>
      <div className={s.branchList}>
        {local.length > 0 && <div className={s.branchGroup}>로컬 브랜치</div>}
        {local.map((b) => (
          <button key={b.name} type="button" className={s.branchItem} data-current={b.name === info.branch || undefined} disabled={busy || b.name === info.branch} onClick={() => onPick(b.name)}>
            <BranchIcon />
            <span className={s.branchItemName}>{b.name}</span>
            <span className={s.muted}>{b.name === info.branch ? '현재 브랜치' : b.upstream || b.sha}</span>
          </button>
        ))}
        {remote.length > 0 && <div className={s.branchGroup}>원격 브랜치</div>}
        {remote.map((b) => (
          <button key={b.name} type="button" className={s.branchItem} disabled={busy} onClick={() => onPick(b.name)}>
            <CloudIcon />
            <span className={s.branchItemName}>{b.name}</span>
            <span className={s.muted}>{b.sha}</span>
          </button>
        ))}
        {!info.hasCommit && <div className={s.muted}>아직 커밋이 없어요. 새 브랜치를 만들면 현재 브랜치 이름이 바뀌어요.</div>}
        {info.hasCommit && local.length === 0 && remote.length === 0 && <div className={s.muted}>일치하는 브랜치가 없어요.</div>}
      </div>
    </Dialog>
  )
}
