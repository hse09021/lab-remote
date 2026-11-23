import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { codeChatQuery, codeFilesQuery, commitsQuery } from '@/api/code'
import { ErrorState, LoadingState, Toast } from '@/components'
import { useToast } from '@/lib/useToast'
import s from './Mobile.module.css'

/** 양쪽 글을 줄 단위로 맞춰 바뀐 줄만 추려요 (Monaco 없이) */
function diffLines(original: string, modified: string) {
  const a = original.split('\n')
  const b = modified.split('\n')
  const out: Array<{ kind: 'same' | 'add' | 'del'; text: string }> = []

  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const left = a[i]
    const right = b[i]
    if (left === right) {
      if (left !== undefined) out.push({ kind: 'same', text: left })
      continue
    }
    if (left !== undefined) out.push({ kind: 'del', text: left })
    if (right !== undefined) out.push({ kind: 'add', text: right })
  }
  return out
}

/** 바뀐 줄 둘레만 보여 줘요 */
function aroundChanges(lines: ReturnType<typeof diffLines>, pad = 1) {
  const keep = new Set<number>()
  lines.forEach((l, i) => {
    if (l.kind === 'same') return
    for (let j = Math.max(0, i - pad); j <= Math.min(lines.length - 1, i + pad); j++) {
      keep.add(j)
    }
  })
  return lines.filter((_, i) => keep.has(i))
}

export function MobileCode() {
  const [files, commits, chat] = useQueries({
    queries: [codeFilesQuery(), commitsQuery(), codeChatQuery()],
  })

  const toast = useToast(2600)
  const [draft, setDraft] = useState('')
  const [sent, setSent] = useState<string[]>([])

  if (files.isPending) return <LoadingState label="변경 내용을 불러오는 중이에요…" />
  if (files.isError || !files.data) {
    return (
      <ErrorState
        title="변경 내용을 불러오지 못했어요"
        error={files.error}
        onRetry={() => void files.refetch()}
      />
    )
  }

  const changed = files.data.find((f) => f.original && f.original !== f.content)
  const lines = changed ? aroundChanges(diffLines(changed.original!, changed.content)) : []
  const branch = commits.data?.[0]?.branch ?? 'main'

  return (
    <div className={s.page}>
      {/* 브랜치 변경 */}
      <section className={s.card} aria-label="브랜치 변경">
        <div className={s.branchHead}>
          <span className={s.branch}>{branch}</span>
          <span className={s.branchNote}>main보다 {commits.data?.length ?? 0}커밋 앞섬</span>
        </div>

        {changed ? (
          <>
            <span className={s.diffFile}>
              {changed.path}
              <span className={s.diffMark}>M</span>
            </span>
            <pre className={s.diff}>
              {lines.map((l, i) => (
                <span
                  key={i}
                  className={`${s.diffLine} ${
                    l.kind === 'add' ? s.diffAdd : l.kind === 'del' ? s.diffDel : ''
                  }`}
                >
                  {l.kind === 'add' ? '+' : l.kind === 'del' ? '-' : ' '} {l.text}
                </span>
              ))}
            </pre>
            {changed.banner && (
              <span className={s.sheetNote}>
                {changed.banner.title} · {changed.banner.text}
              </span>
            )}
          </>
        ) : (
          <p className={s.sheetText}>바뀐 파일이 없어요.</p>
        )}

        <div className={s.actions}>
          <button
            type="button"
            onClick={() => toast.show('전체 변경은 PC에서 봐요')}
            className={s.actionBtn}
          >
            전체 변경 보기
          </button>
          <button
            type="button"
            onClick={() => toast.show('목업이라 PR은 아직 열리지 않아요')}
            className={s.actionBtn}
          >
            PR 열기
          </button>
        </div>
      </section>

      {/* 커밋 */}
      <section className={s.card} aria-label="커밋">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>커밋</span>
        </div>
        <ul className={s.queue}>
          {(commits.data ?? []).map((c) => (
            <li key={c.sha} className={s.commitRow}>
              <span className={s.commitMsg}>{c.msg}</span>
              <span className={s.commitMeta}>
                {c.sha} · {c.author} · {c.branch}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* Claude Code 요청 */}
      <section className={s.card} aria-label="Claude Code">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Claude Code</span>
          <span className={s.cardNote}>{chat.data?.session}</span>
        </div>

        {(chat.data?.messages ?? []).slice(0, 2).map((m, i) =>
          m.kind === 'user' ? (
            <span key={i} className={s.chatUser}>
              {m.text}
            </span>
          ) : (
            <span key={i} className={s.chatLine}>
              {'text' in m ? m.text : ''}
            </span>
          ),
        )}

        {sent.map((t, i) => (
          <span key={`sent-${i}`} className={s.chatUser}>
            {t}
          </span>
        ))}
        {sent.length > 0 && (
          <span className={s.sheetNote}>요청을 받았어요 · PC와 같은 세션에서 처리해요</span>
        )}

        <div className={s.composer}>
          <label htmlFor="mobile-code-chat" className={s.srOnly}>
            Claude Code에 요청하기
          </label>
          <textarea
            id="mobile-code-chat"
            rows={2}
            value={draft}
            placeholder="Claude Code에 요청하기"
            onChange={(e) => setDraft(e.target.value)}
            className={s.textarea}
          />
          <div className={s.composerRow}>
            <button
              type="button"
              onClick={() => {
                const text = draft.trim()
                if (!text) return
                setSent((prev) => [...prev, text])
                setDraft('')
              }}
              className={s.send}
            >
              보내기
            </button>
          </div>
        </div>
      </section>

      <p className={s.footNote}>코드 편집은 PC에서 · 모바일은 확인과 요청 위주예요</p>

      <Toast message={toast.message} placement="bottom" />
    </div>
  )
}
