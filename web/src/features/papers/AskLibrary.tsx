import { Fragment, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { askIsLive, askJobQuery, useAskLibrary } from '@/api/papers'
import type { ChatSource, LibraryChat, LibraryChatMessage } from '@/api/types'
import { Button, VisuallyHidden } from '@/components'
import s from './AskLibrary.module.css'

interface Props {
  chat: LibraryChat | undefined
  /** 요약 패널이 열려 있으면 그 폭만큼 왼쪽으로 비켜요 */
  offsetRight?: number
}

/**
 * 오른쪽 아래 떠 있는 "라이브러리에 묻기".
 * 답변의 인용마다 근거 링크를 붙여요 (docs/spec.md II-1).
 */
const LIVE_HEAD = {
  title: '라이브러리에 묻기',
  caption: 'vault의 논문 노트를 읽고 답해요 · 읽기만 해요 · 대화는 저장하지 않아요',
}

export function AskLibrary({ chat, offsetRight = 0 }: Props) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  // 28px(기본 여백) + 패널 폭
  const shift = { right: 28 + offsetRight }

  // 실제 API — 이 창 안에서만 이어지는 대화
  const live = askIsLive()
  const [log, setLog] = useState<LibraryChatMessage[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const ask = useAskLibrary()
  const job = useQuery(askJobQuery(jobId))
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const d = job.data
    if (!d || d.state === 'running') return
    const sources: ChatSource[] = d.sources.map((x) => ({ label: x.label, paperId: x.paperId }))
    setLog((old) => [...old, { role: 'assistant', text: d.state === 'done' ? d.answer : `답하지 못했어요 — ${d.error}`, sources }])
    setJobId(null)
  }, [job.data])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [log.length, jobId])

  const busy = ask.isPending || !!jobId
  const send = () => {
    const q = draft.trim()
    if (!q || busy) return
    const history = log.map((m) => ({ role: m.role, text: m.text }))
    setLog((old) => [...old, { role: 'user', text: q, sources: [] }])
    setDraft('')
    ask.mutate(
      { question: q, history },
      {
        onSuccess: (j) => setJobId(j.id),
        onError: (e) =>
          setLog((old) => [...old, { role: 'assistant', text: e instanceof ApiError ? e.message : String(e), sources: [] }]),
      },
    )
  }

  const head = live ? LIVE_HEAD : chat
  const messages = live ? log : (chat?.messages ?? [])

  return (
    <>
      {open && head && (
        <section aria-label={head.title} style={shift} className={s.panel}>
          <div className={s.head}>
            <span className={s.title}>{head.title}</span>
            <span className={s.caption}>{head.caption}</span>
          </div>

          <div className={s.log} ref={logRef}>
            {live && messages.length === 0 && (
              <div className={s.assistant}>예: "LoRA 계열 논문들이 rank를 어떻게 정하는지 비교해 줘". 보내기를 누를 때만 Claude에게 가요.</div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? s.user : s.assistant}>
                {m.text}
                {m.sources.map((src, j) => (
                  <Fragment key={src.paperId}>
                    {j === 0 ? ' ' : ' · '}
                    <Link to={`/papers/${encodeURIComponent(src.paperId)}`} className={s.source}>
                      {src.label}
                    </Link>
                  </Fragment>
                ))}
              </div>
            ))}
            {busy && <div className={s.assistant}>vault를 읽는 중이에요… (1분쯤 걸릴 수 있어요)</div>}
          </div>

          <div className={s.composer}>
            <VisuallyHidden>
              <label htmlFor="lib-ask">라이브러리에 질문하기</label>
            </VisuallyHidden>
            <input
              id="lib-ask"
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) send()
              }}
              placeholder="질문하기"
              className={s.input}
            />
            <Button variant="accent" disabled={!live || busy || !draft.trim()} onClick={send}>
              {busy ? '답하는 중…' : '보내기'}
            </Button>
          </div>
        </section>
      )}

      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={shift}
        className={s.fab}
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 18l-1.5 3.5L8 20a8.5 8.5 0 10-3-2z" />
          <path d="M9 11h6M9 14h4" />
        </svg>
        {open ? '닫기' : '라이브러리에 묻기'}
      </button>
    </>
  )
}
