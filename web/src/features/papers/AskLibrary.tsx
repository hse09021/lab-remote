import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import type { LibraryChat } from '@/api/types'
import { Button, VisuallyHidden } from '@/components'
import s from './AskLibrary.module.css'

interface Props {
  chat: LibraryChat | undefined
}

/**
 * 오른쪽 아래 떠 있는 "라이브러리에 묻기".
 * 답변의 인용마다 근거 링크를 붙여요 (docs/spec.md II-1).
 */
export function AskLibrary({ chat }: Props) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  return (
    <>
      {open && chat && (
        <section aria-label={chat.title} className={s.panel}>
          <div className={s.head}>
            <span className={s.title}>{chat.title}</span>
            <span className={s.caption}>{chat.caption}</span>
          </div>

          <div className={s.log}>
            {chat.messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? s.user : s.assistant}>
                {m.text}
                {m.sources.map((src, j) => (
                  <Fragment key={src.paperId}>
                    {j === 0 ? ' ' : ' · '}
                    <Link to={`/papers/${src.paperId}`} className={s.source}>
                      {src.label}
                    </Link>
                  </Fragment>
                ))}
              </div>
            ))}
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
              placeholder="질문하기"
              className={s.input}
            />
            <Button variant="accent">보내기</Button>
          </div>
        </section>
      )}

      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
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
