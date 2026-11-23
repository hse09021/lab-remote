import { useCallback, useRef, useState } from 'react'
import { runReaderAi } from '@/api/papers'
import type { ExplainResult } from '@/api/papers'
import type { ChatEntry, PaperSection, Topic } from '@/api/types'

export interface ChatAnchor {
  /** 연 자리 — 최소화하면 여기 아래에 알약으로 접혀요 */
  x: number
  y: number
  width: number
}

export interface FloatingChatState {
  open: boolean
  minimized: boolean
  topicKey: string | null
  anchor: ChatAnchor | null
  log: ChatEntry[]
  asked: Record<string, true>
  /** 메모 카드에서 열었을 때 붙는 맥락 (실시간 모드에서는 고른 글) */
  context: string | null
  /** 실시간 모드 — 서버가 만든 설명 */
  liveTopic: Topic | null
}

const EMPTY: FloatingChatState = {
  open: false,
  minimized: false,
  topicKey: null,
  anchor: null,
  log: [],
  asked: {},
  context: null,
  liveTopic: null,
}

/** 목업처럼 답이 조금 늦게 와요 */
const ANSWER_DELAY = 900

/** 미리 써 둔 설명이 없는 논문(vault) — 서버에 물어요 */
export interface LiveChat {
  paperId: string
}

const toTopic = (r: ExplainResult): Topic => ({
  title: r.title || '설명',
  blocks: (r.paragraphs ?? []).map((p) => ({ p })),
  qs: (r.questions ?? []).map((q) => ({ q, a: '', go: '', src: '' })),
})

export function useFloatingChat(topics: Record<string, Topic>, sections: PaperSection[] = [], live: LiveChat | null = null) {
  const [state, setState] = useState<FloatingChatState>(EMPTY)
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([])
  // 늦게 온 답이 다른 대화를 덮지 않게
  const seq = useRef(0)
  // 앞 대화 · 고른 글을 보낼 때 읽는 지금 상태
  const now = useRef(state)
  now.current = state

  const open = useCallback(
    (topicKey: string, anchor: ChatAnchor | null, context: string | null = null) => {
      const n = ++seq.current
      const sec = sections.find((x) => x.id === topicKey)
      const needLive = !!live && !topics[topicKey]
      const kind = sec ? 'section' : context ? 'selection' : null
      setState({
        open: true,
        minimized: false,
        topicKey,
        anchor,
        log: [],
        asked: {},
        context,
        liveTopic: needLive
          ? kind
            ? { title: sec ? `${sec.n ? `§${sec.n} ` : ''}${sec.title}` : '고른 글', blocks: [{ p: 'Claude 가 논문을 읽는 중이에요…' }], qs: [] }
            : { title: '이 논문에 묻기', blocks: [{ p: '아래에 질문을 적으면 Claude 가 이 논문을 읽고 답해요.' }], qs: [] }
          : null,
      })
      if (!needLive || !kind || !live) return
      runReaderAi<ExplainResult>(live.paperId, {
        kind,
        section: sec ? `${sec.n ? `${sec.n} ` : ''}${sec.title}` : '',
        text: context ?? '',
        page: sec?.page ?? 0,
      })
        .then((r) => n === seq.current && setState((p) => ({ ...p, liveTopic: toTopic(r) })))
        .catch(
          (e: unknown) =>
            n === seq.current &&
            setState((p) => ({ ...p, liveTopic: { title: '설명하지 못했어요', blocks: [{ p: e instanceof Error ? e.message : String(e) }], qs: [] } })),
        )
    },
    [live, sections, topics],
  )

  const close = useCallback(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
    setState(EMPTY)
  }, [])

  const clearLog = useCallback(() => {
    setState((p) => ({ ...p, log: [], asked: {} }))
  }, [])

  const minimize = useCallback(() => setState((p) => ({ ...p, minimized: true })), [])
  const restore = useCallback(() => setState((p) => ({ ...p, minimized: false })), [])

  /** 추천 질문을 누르거나 직접 입력했을 때 */
  const ask = useCallback(
    (question: string, canned?: { a: string; go: string; src: string }) => {
      if (live && !canned?.a) {
        // 실시간 — 앞 대화와 고른 글을 같이 보내요
        const n = seq.current
        type Turn = { role: 'user' | 'assistant'; text: string }
        const history = now.current.log.flatMap<Turn>((e) =>
          e.kind === 'user' ? [{ role: 'user', text: e.text }] : e.kind === 'answer' ? [{ role: 'assistant', text: e.text }] : [],
        )
        const context = now.current.context ?? ''
        setState((p) => ({ ...p, log: [...p.log, { kind: 'user', text: question }, { kind: 'loading' }], asked: { ...p.asked, [question]: true } }))
        const finish = (text: string) =>
          n === seq.current &&
          setState((p) => {
            const log = [...p.log]
            const i = log.findIndex((e) => e.kind === 'loading')
            const answer: ChatEntry = { kind: 'answer', text }
            if (i >= 0) log[i] = answer
            else log.push(answer)
            return { ...p, log }
          })
        runReaderAi<ExplainResult>(live.paperId, { kind: 'ask', question, history, text: context })
          .then((r) => finish((r.paragraphs ?? []).join('\n\n') || r.title))
          .catch((e: unknown) => finish(`답하지 못했어요 — ${e instanceof Error ? e.message : String(e)}`))
        return
      }
      setState((p) => ({
        ...p,
        log: [...p.log, { kind: 'user', text: question }, { kind: 'loading' }],
        asked: { ...p.asked, [question]: true },
      }))
      const t = setTimeout(() => {
        setState((p) => {
          const log = [...p.log]
          const i = log.findIndex((e) => e.kind === 'loading')
          const answer: ChatEntry = canned
            ? { kind: 'answer', text: canned.a, go: canned.go, src: canned.src }
            : {
                kind: 'answer',
                text: '목업이라 실제 답변은 연결돼 있지 않아요. 서버가 붙으면 여기로 답이 와요.',
              }
          if (i >= 0) log[i] = answer
          else log.push(answer)
          return { ...p, log }
        })
      }, ANSWER_DELAY)
      timers.current.push(t)
    },
    [live],
  )

  /**
   * 미리 써 둔 설명이 없는 섹션은 목업처럼 안내 문단 하나를 보여 줘요.
   * (예: §3.4 — 실제로는 Claude 가 그 섹션 본문을 읽고 풀어 써요)
   */
  const topic = state.topicKey
    ? (topics[state.topicKey] ?? state.liveTopic ?? fallbackTopic(state.topicKey, sections))
    : undefined

  return { state, topic, open, close, clearLog, minimize, restore, ask }
}

/**
 * 섹션 id 를 설명 주제로 바꿔요.
 * 목업처럼 일부 섹션은 그림·수식 설명으로 이어져요.
 */
const ALIAS: Record<string, string> = {
  's3-1': 's3',
  's3-2': 'fig2',
  's3-2-1': 'eq1',
  's3-2-2': 'mh',
  's3-3': 'ffn',
  's3-5': 'pe',
  's5-3': 'lr',
}

export function topicKeyFor(key: string, topics: Record<string, Topic>): string {
  const mapped = ALIAS[key] ?? key
  return topics[mapped] ? mapped : key
}

function fallbackTopic(topicKey: string, sections: PaperSection[]): Topic {
  const sec = sections.find((x) => x.id === topicKey)
  return {
    title: sec ? `${sec.n ? `§${sec.n} ` : ""}${sec.title} 풀어보기` : '설명',
    blocks: [
      { p: '이 섹션 설명은 목업에 미리 넣지 않았어요. 실제로는 Claude가 이 섹션 본문을 읽고 여기에 풀어 써요.' },
    ],
    qs: [],
  }
}
