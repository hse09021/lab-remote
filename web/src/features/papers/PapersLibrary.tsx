import { useRef, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  libraryChatQuery,
  paperPdfHref,
  paperSummariesQuery,
  papersQuery,
  summaryDraftsQuery,
  collectionsQuery,
  fetchBibtex,
  trashQuery,
  useAddArxiv,
  usePaperActions,
  notesQuery,
  useMakeSummary,
  useSummaryJob,
  askIsLive,
  useSaveSummaryMd,
  useSetReadStatus,
  useUploadPdf,
  vaultQuery,
} from '@/api/papers'
import type { AddedPaper } from '@/api/papers'
import { ApiError } from '@/api/client'
import type { Paper, ReadStatus } from '@/api/types'
import {
  Button,
  CollapsedRail,
  Dialog,
  dialogStyles as ds,
  DataTable,
  ErrorState,
  IconButton,
  LoadingState,
  Resizer,
  SegmentedControl,
  SplitButton,
  StatusPill,
  TagChip,
  VisuallyHidden,
} from '@/components'
import type { Column, SegmentedItem } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { AskLibrary } from './AskLibrary'
import { LibrarySidebar, libraryView } from './LibrarySidebar'
import type { LibraryView } from './LibrarySidebar'
import PaperGraph, { PapersViewSwitch } from './PaperGraph'
import { PaperSummaryPane } from './PaperSummaryPane'
import type { SummaryView } from './PaperSummaryPane'
import s from './PapersLibrary.module.css'
import { useIsMobile } from '@/lib/useMediaQuery'
import { MobilePapers } from '../mobile/MobilePapers'
import { copyText } from '@/lib/clipboard'
import { VaultDialog } from './VaultDialog'

type Density = 'list' | 'compact'

const DENSITY_ITEMS: SegmentedItem<Density>[] = [
  { value: 'list', label: <ListIcon />, ariaLabel: '자세히 보기' },
  { value: 'compact', label: <CompactIcon />, ariaLabel: '간단히 보기' },
]

/** `/papers?view=list|graph` — 라이브러리 제목 옆 List / Graph 전환 (PLAN 3장) */
export default function PapersLibrary() {
  const isMobile = useIsMobile()
  const [params] = useSearchParams()
  if (isMobile) return <MobilePapers />
  return params.get('view') === 'graph' ? <PaperGraph /> : <PapersList />
}

function PapersList() {
  const saveMd = useSaveSummaryMd()
  const nav = usePaneResize({ initial: 250, min: 200, max: 400, dir: 1, collapsible: true })
  const drawer = usePaneResize({ initial: 400, min: 320, max: 720, dir: -1 })

  const [view, setView] = useState<LibraryView>('recent')
  const [search, setSearch] = useState('')
  const [density, setDensity] = useState<Density>('list')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [openSummaryId, setOpenSummaryId] = useState<string | null>('attn')
  const [summaryView, setSummaryView] = useState<SummaryView>('nice')
  // 요약 MD 수정본은 저장소에 있어요 — 리더와 같은 값을 보고, 새로 고쳐도 남아요
  const [mdEdits, setMdEdits] = useState<Record<string, string>>({})
  const [vaultOpen, setVaultOpen] = useState(false)
  const addArxiv = useAddArxiv()
  const uploadPdf = useUploadPdf()
  const fileInput = useRef<HTMLInputElement>(null)
  const [added, setAdded] = useState<{ text: string; tone: 'ok' | 'err' } | null>(null)
  const cols = useQuery(collectionsQuery())
  const notes = useQuery(notesQuery())
  const makeSummary = useMakeSummary()
  const live = askIsLive()
  const trash = useQuery(trashQuery())
  const act = usePaperActions()
  const [colDialog, setColDialog] = useState<'' | 'add' | { remove: string }>('')
  const [colName, setColName] = useState('')
  const [filterOpen, setFilterOpen] = useState(false)
  const [filters, setFilters] = useState({ source: 'all' as 'all' | 'arxiv-html' | 'pdf', hasPdf: false, hasSummary: false })
  const filterCount = (filters.source !== 'all' ? 1 : 0) + (filters.hasPdf ? 1 : 0) + (filters.hasSummary ? 1 : 0)
  const onAdded = (r: AddedPaper) => {
    setAdded({
      text: r.created
        ? `추가했어요 · ${r.path}${r.pdf === false ? ' (PDF는 다운로드하지 못했어요)' : ''}`
        : `이미 있는 논문이에요 · ${r.path}`,
      tone: 'ok',
    })
    setOpenSummaryId(r.id)
  }
  const onFail = (e: unknown) => setAdded({ text: e instanceof ApiError ? e.message : String(e), tone: 'err' })

  const [papers, summaries, chat, mdDrafts] = useQueries({
    queries: [
      papersQuery(),
      paperSummariesQuery(),
      libraryChatQuery(),
      summaryDraftsQuery(),
    ],
  })
  const setStatus = useSetReadStatus()
  const vault = useQuery(vaultQuery())

  const query = search.trim().toLowerCase()
  const source = view === 'trash' ? trash.data : papers.data
  const rows = (source ?? [])
    .filter(libraryView(view).test)
    .filter((p) => filters.source === 'all' || p.source === filters.source)
    .filter((p) => !filters.hasPdf || p.hasPdf)
    .filter((p) => !filters.hasSummary || p.summaryState === 'done')
    .filter(
      (p) =>
        !query ||
        p.title.toLowerCase().includes(query) ||
        p.authors.toLowerCase().includes(query) ||
        (p.field ?? '').toLowerCase().includes(query) ||
        (p.model ?? '').toLowerCase().includes(query),
    )

  const selectedIds = Object.entries(selected)
    .filter(([, on]) => on)
    .map(([id]) => id)
  const selectedCount = selectedIds.length

  // 요약 — AI 요약이 있으면 그것, 없으면 vault 노트 본문(읽기만)
  const hasSummary = (id: string) => Boolean(summaries.data?.[id] || notes.data?.[id])
  // 요약이 있는 논문만 이전/다음으로 돌아요
  const order = (papers.data ?? []).filter((p) => hasSummary(p.id)).map((p) => p.id)
  const inList = (papers.data ?? []).some((p) => p.id === openSummaryId)
  const openSummary = openSummaryId && inList ? summaries.data?.[openSummaryId] : undefined
  const openNote =
    openSummaryId && inList && !openSummary ? (papers.data ?? []).find((p) => p.id === openSummaryId) : undefined
  const noteBody = openNote ? notes.data?.[openNote.id] : undefined
  const drawerOpen = Boolean(openSummary || (openNote && noteBody !== undefined))
  const step = (delta: number) => {
    if (!openSummaryId || order.length === 0) return
    const i = order.indexOf(openSummaryId)
    const next = order[(i + delta + order.length) % order.length]
    if (next) setOpenSummaryId(next)
  }

  const columns: Column<Paper>[] = [
    {
      key: 'select',
      label: '선택',
      // 목업 32px(내용) + 좌우 패딩 16 = 48 (이 열은 테두리가 없어요)
      width: 48,
      headerHidden: true,
      render: (p) => (
        <input
          type="checkbox"
          checked={selected[p.id] ?? false}
          onChange={() => setSelected((prev) => ({ ...prev, [p.id]: !prev[p.id] }))}
          aria-label={`${p.title} 선택`}
          className={s.checkbox}
        />
      ),
    },
    {
      key: 'title',
      label: '제목',
      render: (p) => (
        <div className={s.titleCell}>
          <Link to={`/papers/${p.id}`} className={s.titleLink}>
            {p.title}
          </Link>
          {density === 'list' && (
            <span className={s.paperMeta}>
              {p.authors} · {p.venue} · {p.source === 'arxiv-html' ? 'arXiv HTML' : 'PDF'}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      label: '상태',
      // 목업 110px(내용) + 패딩 24 + 테두리 1
      width: 135,
      render: (p) => (
        <StatusPill
          status={p.status}
          size="lg"
          label={`${p.title} 읽음 상태`}
          onChange={(status: ReadStatus) => setStatus.mutate({ id: p.id, status })}
        />
      ),
    },
    {
      key: 'tags',
      label: '태그',
      width: 195,
      render: (p) =>
        p.field || p.model ? (
          <div className={s.tags}>
            {p.field && <TagChip>{p.field}</TagChip>}
            {p.model && <TagChip>{p.model}</TagChip>}
          </div>
        ) : (
          // 보관만 해 둔 논문 — 아직 태그가 없어요
          <span className={s.pendingTag}>분류 대기</span>
        ),
    },
    {
      key: 'summary',
      label: '요약',
      width: 125,
      render: (p) => {
        if (p.summaryState === 'done') {
          return (
            <button
              type="button"
              aria-pressed={openSummaryId === p.id}
              aria-label={`${p.title} 요약 MD 보기`}
              onClick={() => setOpenSummaryId(p.id)}
              className={s.summaryBtn}
            >
              요약 MD
            </button>
          )
        }
        if (p.summaryState === 'running') {
          return <SummaryRunning id={p.id} />
        }
        if (!live) return <span className={s.summaryNone}>—</span>
        return (
          <button
            type="button"
            className={s.makeSummary}
            disabled={makeSummary.isPending}
            title="Claude가 노트와 PDF를 읽고 요약해요 · vault에 '이름 요약.md'를 새로 만들어요"
            onClick={() =>
              makeSummary.mutate(p.id, {
                onSuccess: () => setAdded({ text: `${p.title} 요약을 만드는 중이에요 · 1~2분 걸려요`, tone: 'ok' }),
                onError: onFail,
              })
            }
          >
            요약 만들기
          </button>
        )
      },
    },
    {
      key: 'access',
      label: '마지막 접근',
      width: 135,
      render: (p) => <span className={s.access}>{p.access}</span>,
    },
  ]

  return (
    <>
      {nav.closed && (
        <CollapsedRail side="left" label="사이드바 펼치기" onExpand={nav.toggle} />
      )}
      <LibrarySidebar
        style={nav.style}
        onCollapse={nav.toggle}
        papers={papers.data}
        view={view}
        onViewChange={setView}
        search={search}
        onSearchChange={setSearch}
        vaultPath={vault.data?.path}
        onVault={() => setVaultOpen(true)}
        collections={cols.data}
        onAddCollection={() => {
          setColName('')
          setColDialog('add')
        }}
        onRemoveCollection={(name) => setColDialog({ remove: name })}
        trashCount={trash.data?.length}
      />
      <Resizer handle={nav.resizerProps} label="라이브러리 메뉴 너비 조절" />

      <main className={s.main}>
        <div className={s.toolbar}>
          <div className={s.titleRow}>
            <h1 className={s.title}>{libraryView(view).title}</h1>
            <PapersViewSwitch current="list" />
          </div>
          <div className={s.tools}>
            <SegmentedControl
              items={DENSITY_ITEMS}
              value={density}
              onChange={setDensity}
              label="보기 방식"
              variant="icon"
            />
            <IconButton label={filterCount ? `필터 ${filterCount}개 적용됨` : '필터'} size={42} aria-expanded={filterOpen} onClick={() => setFilterOpen((v) => !v)}>
              <FilterIcon />
            </IconButton>
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                setAdded({ text: `${file.name} 업로드하는 중이에요…`, tone: 'ok' })
                uploadPdf.mutate(file, { onSuccess: onAdded, onError: onFail })
              }}
            />
            <SplitButton
              label="논문 업로드"
              menuLabel="논문 업로드"
              menuWidth={380}
              onClick={() => fileInput.current?.click()}
              items={[{ label: 'PDF 파일 업로드', onSelect: () => fileInput.current?.click() }]}
              footer={
                <UrlUploadRow
                  busy={addArxiv.isPending}
                  onAdd={(url) => {
                    setAdded({ text: 'arXiv에서 가져오는 중이에요…', tone: 'ok' })
                    addArxiv.mutate(url, { onSuccess: onAdded, onError: onFail })
                  }}
                />
              }
            />
          </div>
        </div>

        {filterOpen && (
          <div className={s.filterBar} role="group" aria-label="필터">
            <span className={s.filterLabel}>출처</span>
            {(
              [
                ['all', '모두'],
                ['arxiv-html', 'arXiv'],
                ['pdf', 'PDF'],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={filters.source === v}
                className={s.filterChip}
                onClick={() => setFilters((f) => ({ ...f, source: v }))}
              >
                {label}
              </button>
            ))}
            <label className={s.filterCheck}>
              <input type="checkbox" checked={filters.hasPdf} onChange={(e) => setFilters((f) => ({ ...f, hasPdf: e.target.checked }))} />
              PDF 있음
            </label>
            <label className={s.filterCheck}>
              <input
                type="checkbox"
                checked={filters.hasSummary}
                onChange={(e) => setFilters((f) => ({ ...f, hasSummary: e.target.checked }))}
              />
              요약 있음
            </label>
            {filterCount > 0 && (
              <button type="button" className={s.filterReset} onClick={() => setFilters({ source: 'all', hasPdf: false, hasSummary: false })}>
                필터 해제
              </button>
            )}
          </div>
        )}

        {added && (
          <div role="status" className={s.addedBar} data-tone={added.tone}>
            <span>{added.text}</span>
            <button type="button" className={s.addedClose} aria-label="알림 닫기" onClick={() => setAdded(null)}>
              ×
            </button>
          </div>
        )}

        {papers.isError ? (
          <ErrorState
            title="논문 목록을 불러오지 못했어요"
            error={papers.error}
            onRetry={() => void papers.refetch()}
          />
        ) : papers.data ? (
          <DataTable
            label="논문 목록"
            columns={columns}
            rows={rows}
            rowKey={(p) => p.id}
            cellY={density === 'list' ? 16 : 9}
            headY={12}
            flushEdges={false}
            minWidth={820}
            emptyMessage={
              papers.data.length === 0
                ? `vault에 논문 노트가 없어요 — ${vault.data?.path ?? 'vault'}/Papers/에 MD 파일을 넣거나, 사이드바의 'vault 위치'에서 폴더를 지정해 주세요.`
                : '조건에 맞는 논문이 없어요.'
            }
          />
        ) : (
          <LoadingState label="논문 목록을 불러오는 중이에요…" />
        )}

        {selectedCount > 0 && (
          <div className={s.selectionBar}>
            <span className={s.selectionCount}>{selectedCount}편 선택됨</span>
            {view !== 'trash' && (cols.data?.length ?? 0) > 0 && (
              <select
                aria-label="모음에 넣기"
                className={s.onDarkSelect}
                value=""
                onChange={(e) => {
                  const name = e.target.value
                  if (!name) return
                  act.setMembers.mutate({ name, ids: selectedIds, on: true }, { onSuccess: () => setAdded({ text: `${selectedCount}편을 '${name}' 모음에 넣었어요`, tone: 'ok' }) })
                }}
              >
                <option value="">모음에 넣기…</option>
                {cols.data?.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            {view.startsWith('col:') && (
              <button
                type="button"
                className={s.onDark}
                onClick={() => {
                  act.setMembers.mutate({ name: view.slice(4), ids: selectedIds, on: false })
                  setSelected({})
                }}
              >
                모음에서 빼기
              </button>
            )}
            {view === 'trash' ? (
              <button
                type="button"
                className={s.onDark}
                onClick={() => {
                  act.trash.mutate({ ids: selectedIds, on: false })
                  setSelected({})
                }}
              >
                되돌리기
              </button>
            ) : (
              <button
                type="button"
                className={s.onDark}
                onClick={() => {
                  act.trash.mutate({ ids: selectedIds, on: true })
                  setAdded({ text: `${selectedCount}편을 휴지통으로 옮겼어요 · vault 파일은 그대로 있어요`, tone: 'ok' })
                  setSelected({})
                }}
              >
                휴지통
              </button>
            )}
            <button
              type="button"
              className={s.onDark}
              onClick={() => {
                const chosen = (source ?? []).filter((p) => selectedIds.includes(p.id))
                fetchBibtex(chosen)
                  .then((text) => copyText(text))
                  .then(() => setAdded({ text: `${chosen.length}편의 BibTeX를 복사했어요`, tone: 'ok' }))
                  .catch(onFail)
              }}
            >
              BibTeX 복사
            </button>
          </div>
        )}

        <Dialog
          open={colDialog === 'add'}
          title="새 모음"
          confirmLabel="만들기"
          busy={act.addCollection.isPending}
          error={act.addCollection.error instanceof ApiError ? act.addCollection.error.message : undefined}
          onClose={() => {
            act.addCollection.reset()
            setColDialog('')
          }}
          onConfirm={() =>
            act.addCollection.mutate(colName.trim(), {
              onSuccess: () => {
                setColDialog('')
                setView(`col:${colName.trim()}`)
              },
            })
          }
        >
          <label className={ds.field}>
            모음 이름
            <input className={ds.input} value={colName} onChange={(e) => setColName(e.target.value)} placeholder="LoRA 계열" autoFocus />
          </label>
          <span>모음은 lab.remote에만 저장돼요. vault 파일은 옮기지 않아요. 논문을 선택한 뒤 아래 선택 바에서 넣을 수 있어요.</span>
        </Dialog>
        <Dialog
          open={typeof colDialog === 'object'}
          title={typeof colDialog === 'object' ? `'${colDialog.remove}' 모음 지우기` : ''}
          confirmLabel="지우기"
          tone="danger"
          busy={act.removeCollection.isPending}
          onClose={() => setColDialog('')}
          onConfirm={() => {
            if (typeof colDialog !== 'object') return
            act.removeCollection.mutate(colDialog.remove, {
              onSuccess: () => {
                if (view === `col:${colDialog.remove}`) setView('all')
                setColDialog('')
              },
            })
          }}
        >
          <span>모음만 지워요. 안에 있던 논문은 라이브러리에 그대로 있어요.</span>
        </Dialog>

        <AskLibrary
          chat={chat.data}
          offsetRight={drawerOpen ? drawer.size + 12 : 0}
        />
      </main>

      <VaultDialog open={vaultOpen} onClose={() => setVaultOpen(false)} />

      {openNote && noteBody !== undefined && (
        <div className={s.drawerWrap}>
          <Resizer handle={drawer.resizerProps} label="요약 패널 너비 조절" />
          <aside aria-label="논문 노트 미리보기" style={drawer.style} className={s.drawer}>
            <div className={s.drawerHead}>
              <span className={s.drawerTitle}>논문 노트</span>
              <span className={s.drawerPath}>{openNote.path}</span>
              <IconButton label="이전 요약" size={34} variant="outline" onClick={() => step(-1)}>
                <ChevronLeft />
              </IconButton>
              <IconButton label="다음 요약" size={34} variant="outline" onClick={() => step(1)}>
                <ChevronRight />
              </IconButton>
              <IconButton label="요약 닫기" size={34} onClick={() => setOpenSummaryId(null)}>
                <CloseIcon />
              </IconButton>
            </div>
            <div className={s.drawerBody}>
              <h2 className={s.noteTitle}>{openNote.title}</h2>
              <span className={s.paperMeta}>
                {openNote.authors}
                {openNote.venue && ` · ${openNote.venue}`}
              </span>
              <div className={s.noteActions}>
                <Button variant="primary" size="md" padWide href={`/papers/${encodeURIComponent(openNote.id)}`}>
                  리더에서 열기
                </Button>
                <Button variant="outline" size="md" href={`/papers?view=graph&node=${encodeURIComponent(openNote.id)}`}>
                  그래프에서 보기
                </Button>
                {openNote.hasPdf && (
                  <Button variant="outline" size="md" href={paperPdfHref(openNote.id)} target="_blank" rel="noreferrer">
                    PDF
                  </Button>
                )}
              </div>
              <pre className={s.noteBody}>{noteBody}</pre>
              <span className={s.paperMeta}>vault 노트는 읽기 전용이에요. 수정은 Obsidian에서 해 주세요.</span>
              {live && openNote.summaryState !== 'running' && (
                <Button
                  variant="outline"
                  size="md"
                  disabled={makeSummary.isPending}
                  onClick={() =>
                    makeSummary.mutate(openNote.id, {
                      onSuccess: () => setAdded({ text: `${openNote.title} 요약을 만드는 중이에요 · 1~2분 걸려요`, tone: 'ok' }),
                      onError: onFail,
                    })
                  }
                >
                  AI 요약 만들기
                </Button>
              )}
              {openNote.summaryState === 'running' && <span className={s.paperMeta}>Claude가 요약을 만드는 중이에요…</span>}
            </div>
          </aside>
        </div>
      )}

      {openSummary && openSummaryId && (
        <div className={s.drawerWrap}>
          <Resizer handle={drawer.resizerProps} label="요약 패널 너비 조절" />
          <aside aria-label="요약 미리보기" style={drawer.style} className={s.drawer}>
            <div className={s.drawerHead}>
              <span className={s.drawerTitle}>요약 MD</span>
              <span className={s.drawerPath}>{openSummary.path}</span>
              <IconButton label="이전 요약" size={34} variant="outline" onClick={() => step(-1)}>
                <ChevronLeft />
              </IconButton>
              <IconButton label="다음 요약" size={34} variant="outline" onClick={() => step(1)}>
                <ChevronRight />
              </IconButton>
              <IconButton label="요약 닫기" size={34} onClick={() => setOpenSummaryId(null)}>
                <CloseIcon />
              </IconButton>
            </div>

            <div className={s.drawerBody}>
              <PaperSummaryPane
                summary={openSummary}
                view={summaryView}
                onViewChange={setSummaryView}
                draft={mdEdits[openSummaryId] ?? mdDrafts.data?.[openSummaryId] ?? null}
                saved={mdDrafts.data?.[openSummaryId] ?? null}
                onDraftChange={(text) =>
                  setMdEdits((prev) => ({ ...prev, [openSummaryId]: text }))
                }
                onSave={() => {
                  const markdown = mdEdits[openSummaryId] ?? mdDrafts.data?.[openSummaryId]
                  if (markdown !== undefined) {
                    saveMd.mutate({ id: openSummaryId, markdown })
                  }
                  setMdEdits((prev) => {
                    const next = { ...prev }
                    delete next[openSummaryId]
                    return next
                  })
                }}
                textareaId="library-md"
                leadAction={
                  <Button variant="primary" size="md" padWide href={`/papers/${openSummaryId}`}>
                    리더에서 열기
                  </Button>
                }
              />
            </div>
          </aside>
        </div>
      )}
    </>
  )
}

function UrlUploadRow({ busy, onAdd }: { busy: boolean; onAdd: (url: string) => void }) {
  const [url, setUrl] = useState('')
  const submit = () => {
    if (url.trim() && !busy) {
      onAdd(url.trim())
      setUrl('')
    }
  }
  return (
    <>
      <VisuallyHidden>
        <label htmlFor="lib-url">arXiv 링크</label>
      </VisuallyHidden>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          id="lib-url"
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="arXiv 링크 (https://arxiv.org/abs/…)"
        />
        <Button variant="accent" disabled={busy || !url.trim()} onClick={submit}>
          {busy ? '추가하는 중…' : '추가'}
        </Button>
      </div>
      <span>제목 · 저자 · 초록을 가져와 vault의 Papers/에 노트를 만들고 PDF도 다운로드해요</span>
    </>
  )
}

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

function ListIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <rect x="4" y="4" width="16" height="7" rx="1.5" />
      <rect x="4" y="13" width="16" height="7" rx="1.5" />
    </svg>
  )
}
function CompactIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M4 6h16M4 10h16M4 14h16M4 18h16" />
    </svg>
  )
}
function FilterIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" {...st} aria-hidden="true">
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </svg>
  )
}
const ChevronLeft = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...st} strokeWidth="2.2" aria-hidden="true">
    <path d="M15 6l-6 6 6 6" />
  </svg>
)
const ChevronRight = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...st} strokeWidth="2.2" aria-hidden="true">
    <path d="M9 6l6 6-6 6" />
  </svg>
)
const CloseIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} strokeWidth="2" aria-hidden="true">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

/** 만드는 중 — 끝날 때까지 물어보고, 끝나면 목록이 새로 받아요 */
function SummaryRunning({ id }: { id: string }) {
  const job = useSummaryJob(id, true)
  const again = useMakeSummary()
  if (job.data?.state === 'failed') {
    // 실패 사유는 마우스를 올리면 보여요 · 누르면 다시 만들어요
    return (
      <button
        type="button"
        className={s.makeSummary}
        title={`실패했어요 — ${job.data.error}`}
        disabled={again.isPending}
        onClick={() => again.mutate(id)}
      >
        실패 · 다시 만들기
      </button>
    )
  }
  return <span className={s.summaryRunning}>요약 중</span>
}
