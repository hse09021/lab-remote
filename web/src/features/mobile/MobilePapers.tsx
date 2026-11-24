import { Fragment, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import {
  libraryChatQuery,
  paperSummariesQuery,
  papersQuery,
  useSetReadStatus,
} from '@/api/papers'
import type { Paper, PaperSummary, ReadStatus } from '@/api/types'
import { ErrorState, LoadingState, Sheet, StatusPill, Toast } from '@/components'
import { useToast } from '@/lib/useToast'
import { LIVE_HEAD, useLibraryAsk } from '../papers/AskLibrary'
import s from './Mobile.module.css'

const FILTERS: Array<{ id: 'recent' | ReadStatus; label: string }> = [
  { id: 'recent', label: '최근' },
  { id: 'reading', label: '읽는 중' },
  { id: 'todo', label: '읽을 예정' },
  { id: 'done', label: '완료' },
]

export function MobilePapers() {
  // /papers/:id로 바로 들어와도 같은 목록 + 요약 시트예요
  const { id: routeId } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [papers, summaries, chat] = useQueries({
    queries: [papersQuery(), paperSummariesQuery(), libraryChatQuery()],
  })
  const setStatus = useSetReadStatus()
  const toast = useToast(2600)

  const [filter, setFilter] = useState<'recent' | ReadStatus>('recent')
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState<string | null>(routeId ?? null)
  const [askOpen, setAskOpen] = useState(false)
  const [askDraft, setAskDraft] = useState('')
  const ask = useLibraryAsk()

  if (papers.isPending) return <LoadingState label="논문을 불러오는 중이에요…" />
  if (papers.isError || !papers.data) {
    return (
      <ErrorState
        title="논문을 불러오지 못했어요"
        error={papers.error}
        onRetry={() => void papers.refetch()}
      />
    )
  }

  const query = search.trim().toLowerCase()
  const rows = papers.data.filter((p) => {
    if (filter !== 'recent' && p.status !== filter) return false
    if (!query) return true
    return (
      p.title.toLowerCase().includes(query) ||
      p.authors.toLowerCase().includes(query) ||
      (p.field ?? '').toLowerCase().includes(query)
    )
  })

  const open = openId ? papers.data.find((p) => p.id === openId) : undefined

  const closeSheet = () => {
    setOpenId(null)
    // 주소로 들어왔으면 목록으로 되돌려요
    if (routeId) navigate('/papers', { replace: true })
  }

  return (
    <div className={s.page}>
      <label className={s.searchWrap}>
        <span className={s.srOnly}>라이브러리 검색</span>
        <input
          type="search"
          value={search}
          placeholder="라이브러리 검색"
          onChange={(e) => setSearch(e.target.value)}
          className={s.search}
        />
      </label>

      <div className={s.chipRow} role="group" aria-label="읽음 상태 필터">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
            className={s.chip}
          >
            {f.label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className={s.empty}>조건에 맞는 논문이 없어요.</p>
      ) : (
        <ul className={s.cardList}>
          {rows.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => setOpenId(p.id)} className={s.paperCard}>
                <span className={s.paperTitle}>{p.title}</span>
                <span className={s.paperMeta}>
                  {p.authors} · {p.venue}
                </span>
                <span className={s.paperFoot}>
                  <StatusPill status={p.status} size="sm" />
                  <span className={s.paperSum}>
                    {p.summaryState === 'done'
                      ? '요약 있음'
                      : p.summaryState === 'running'
                        ? '요약 중'
                        : '요약 없음'}
                  </span>
                  <span className={s.paperAccess}>{p.access}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className={s.footNote}>논문 읽기와 하이라이트는 PC 리더에서 할 수 있어요</p>

      <button type="button" onClick={() => setAskOpen(true)} className={s.fab}>
        라이브러리에 묻기
      </button>

      {/* 요약 시트 */}
      <Sheet open={!!open} title={open?.title ?? '논문'} onClose={closeSheet}>
        {open && (
          <PaperSheet
            paper={open}
            summary={summaries.data?.[open.id]}
            onStatus={(status) => {
              setStatus.mutate({ id: open.id, status })
              toast.show('읽음 상태를 변경했어요')
            }}
          />
        )}
      </Sheet>

      {/* 라이브러리에 묻기 */}
      <Sheet
        open={askOpen}
        title={ask.live ? LIVE_HEAD.title : (chat.data?.title ?? '라이브러리에 묻기')}
        onClose={() => setAskOpen(false)}
      >
        <p className={s.sheetText}>{ask.live ? LIVE_HEAD.caption : chat.data?.caption}</p>
        {ask.live && ask.log.length === 0 && (
          <span className={s.sheetNote}>보내기를 누를 때만 Claude에게 전송돼요. 답변까지 1분 정도 걸릴 수 있어요.</span>
        )}
        {(ask.live ? ask.log : (chat.data?.messages ?? [])).map((m, i) => (
          <p key={i} className={m.role === 'user' ? s.askUser : s.sheetText}>
            {m.text}
            {m.sources.map((src, j) => (
              <Fragment key={src.paperId}>
                {j === 0 ? ' ' : ' · '}
                <button
                  type="button"
                  className={s.askSource}
                  onClick={() => {
                    setAskOpen(false)
                    setOpenId(src.paperId)
                  }}
                >
                  {src.label}
                </button>
              </Fragment>
            ))}
          </p>
        ))}
        {ask.busy && <span className={s.sheetNote}>vault를 읽는 중이에요…</span>}
        {ask.live ? (
          <form
            className={s.askRow}
            onSubmit={(e) => {
              e.preventDefault()
              if (ask.send(askDraft)) setAskDraft('')
            }}
          >
            <input
              className={s.search}
              value={askDraft}
              onChange={(e) => setAskDraft(e.target.value)}
              placeholder="질문하기"
              aria-label="라이브러리에 질문하기"
            />
            <button type="submit" className={s.askSend} disabled={ask.busy || !askDraft.trim()}>
              {ask.busy ? '답하는 중…' : '보내기'}
            </button>
          </form>
        ) : (
          <span className={s.sheetNote}>서버에 연결되면 vault를 읽고 답해요.</span>
        )}
      </Sheet>

      <Toast message={toast.message} placement="bottom" />
    </div>
  )
}

function PaperSheet({
  paper,
  summary,
  onStatus,
}: {
  paper: Paper
  summary: PaperSummary | undefined
  onStatus: (status: ReadStatus) => void
}) {
  const STATUSES: Array<{ id: ReadStatus; label: string }> = [
    { id: 'todo', label: '읽을 예정' },
    { id: 'reading', label: '읽는 중' },
    { id: 'done', label: '완료' },
  ]

  return (
    <div className={s.sheetBody}>
      <span className={s.sheetMeta}>
        {paper.authors} · {paper.venue}
      </span>

      <div className={s.chipRow} role="radiogroup" aria-label="읽음 상태">
        {STATUSES.map((st) => (
          <button
            key={st.id}
            type="button"
            role="radio"
            aria-checked={paper.status === st.id}
            onClick={() => onStatus(st.id)}
            className={s.chip}
          >
            {st.label}
          </button>
        ))}
      </div>

      {summary && summary.lines.length > 0 ? (
        <>
          <span className={s.sheetSubTitle}>3줄 요약</span>
          <ol className={s.summaryLines}>
            {summary.lines.map((l, i) => (
              <li key={i} className={s.summaryLine}>
                <span className={s.summaryNum}>{i + 1}</span>
                <span className={s.summaryText}>
                  {l.text} <span className={s.summaryRef}>{l.ref}</span>
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className={s.sheetText}>
          {paper.summaryState === 'running' ? '요약을 만드는 중이에요.' : '아직 요약이 없어요.'}
        </p>
      )}

      <span className={s.sheetPath}>{paper.path ?? '아직 요약 없음'}</span>
      <span className={s.sheetNote}>
        본문은 PC 리더에서 열어 주세요. 모바일에서는 본문을 표시하지 않아요.
      </span>
    </div>
  )
}
