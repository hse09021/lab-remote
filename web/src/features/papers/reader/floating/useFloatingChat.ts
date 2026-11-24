import { useCallback, useEffect, useRef, useState } from 'react'
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

/**
 * 닫아도 남는 대화 — 논문마다, 대화(설명 주제 + 고른 글)마다 둬요.
 * X는 창만 닫고, 휴지통을 눌러야 그 대화가 지워져요. 다른 논문에 갔다 와도 남아요(새로 고치면 비워져요).
 */
interface Saved {
  log: ChatEntry[]
  asked: Record<string, true>
  liveTopic: Topic | null
}
const SAVED = new Map<string, Saved>()
const sessionKey = (paper: string, topicKey: string, context: string | null) => `${paper}\u0000${topicKey}\u0000${context ?? ''}`

/** 열린 창이 그 대화가 아니어도 저장소에 답을 넣어요 (창을 닫은 뒤에 온 답) */
function patchSaved(key: string, fn: (s: Saved) => Saved) {
  // 휴지통으로 지운 대화에 늦게 온 답은 버려요
  const cur = SAVED.get(key)
  if (cur) SAVED.set(key, fn(cur))
}

const fillAnswer = (log: ChatEntry[], answer: ChatEntry) => {
  const out = [...log]
  const i = out.findIndex((e) => e.kind === 'loading')
  if (i >= 0) out[i] = answer
  else out.push(answer)
  return out
}

export function useFloatingChat(topics: Record<string, Topic>, sections: PaperSection[] = [], live: LiveChat | null = null) {
  const [state, setState] = useState<FloatingChatState>(EMPTY)
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([])
  // 늦게 온 답이 다른 대화를 덮지 않게
  const seq = useRef(0)
  // 앞 대화 · 고른 글을 보낼 때 읽는 지금 상태
  const now = useRef(state)
  now.current = state
  const paperKey = live?.paperId ?? 'local'
  /** 지금 열린 대화의 키 */
  const current = useRef<string | null>(null)

  // 열린 대화가 바뀔 때마다 저장소에 같이 적어요
  useEffect(() => {
    if (current.current && state.open) {
      SAVED.set(current.current, { log: state.log, asked: state.asked, liveTopic: state.liveTopic })
    }
  }, [state.open, state.log, state.asked, state.liveTopic])

  const open = useCallback(
    (topicKey: string, anchor: ChatAnchor | null, context: string | null = null) => {
      seq.current++
      const sec = sections.find((x) => x.id === topicKey)
      const needLive = !!live && !topics[topicKey]
      // 그림 · 표 · 수식 — `el:<쪽>:<이름>`
      const el = topicKey.match(/^el:(\d+):(.+)$/)
      const kind = sec ? 'section' : el ? 'element' : context ? 'selection' : null
      const key = sessionKey(paperKey, topicKey, context)
      current.current = key
      const saved = SAVED.get(key)
      // 전에 연 대화면 그대로 이어요 — 설명도 다시 묻지 않아요(실패했던 것만 다시)
      const reuse = saved && saved.liveTopic && saved.liveTopic.title !== '설명하지 못했어요'
      if (saved && (reuse || !needLive || !kind)) {
        setState({ open: true, minimized: false, topicKey, anchor, log: saved.log, asked: saved.asked, context, liveTopic: saved.liveTopic })
        return
      }
      setState({
        open: true,
        minimized: false,
        topicKey,
        anchor,
        log: saved?.log ?? [],
        asked: saved?.asked ?? {},
        context,
        liveTopic: needLive
          ? kind
            ? { title: sec ? `${sec.n ? `§${sec.n} ` : ''}${sec.title}` : el ? el[2]! : '고른 글', blocks: [{ p: 'Claude가 논문을 읽는 중이에요…' }], qs: [] }
            : { title: '이 논문에 묻기', blocks: [{ p: '아래에 질문을 적으면 Claude가 이 논문을 읽고 답해요.' }], qs: [] }
          : null,
      })
      if (!needLive || !kind || !live) return
      runReaderAi<ExplainResult>(live.paperId, {
        kind,
        section: sec ? `${sec.n ? `${sec.n} ` : ''}${sec.title}` : el ? el[2]! : '',
        text: context ?? '',
        page: sec?.page ?? (el ? Number(el[1]) : 0),
      })
        .then((r) => {
          const topic = toTopic(r)
          patchSaved(key, (x) => ({ ...x, liveTopic: topic }))
          if (current.current === key) setState((p) => ({ ...p, liveTopic: topic }))
        })
        .catch((e: unknown) => {
          const topic = { title: '설명하지 못했어요', blocks: [{ p: e instanceof Error ? e.message : String(e) }], qs: [] }
          patchSaved(key, (x) => ({ ...x, liveTopic: topic }))
          if (current.current === key) setState((p) => ({ ...p, liveTopic: topic }))
        })
    },
    [live, sections, topics, paperKey],
  )

  /** X — 창만 닫아요. 대화는 저장소에 남아요 */
  const close = useCallback(() => {
    current.current = null
    seq.current++
    setState(EMPTY)
  }, [])

  /** 휴지통 — 이 대화를 설명까지 통째로 지우고 창을 닫아요. 다시 열면 처음부터 설명해요 */
  const clearLog = useCallback(() => {
    if (current.current) SAVED.delete(current.current)
    current.current = null
    seq.current++
    setState(EMPTY)
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
        const key = current.current
        setState((p) => ({ ...p, log: [...p.log, { kind: 'user', text: question }, { kind: 'loading' }], asked: { ...p.asked, [question]: true } }))
        const finish = (text: string) => {
          const answer: ChatEntry = { kind: 'answer', text }
          if (n === seq.current && current.current === key) {
            setState((p) => ({ ...p, log: fillAnswer(p.log, answer) }))
          } else if (key) {
            // 창을 닫은 뒤에 온 답 — 그 대화에 넣어 둬요
            patchSaved(key, (x) => ({ ...x, log: fillAnswer(x.log, answer) }))
          }
        }
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
      const key = current.current
      const t = setTimeout(() => {
        const fill = (p: { log: ChatEntry[] }) => {
          const answer: ChatEntry = canned
            ? { kind: 'answer', text: canned.a, go: canned.go, src: canned.src }
            : {
                kind: 'answer',
                text: '서버 없이 화면만 보는 모드(VITE_USE_MOCK=all)라 미리 써 둔 답만 있어요.',
              }
          return fillAnswer(p.log, answer)
        }
        if (current.current === key) setState((p) => ({ ...p, log: fill(p) }))
        else if (key) patchSaved(key, (x) => ({ ...x, log: fill(x) }))
      }, ANSWER_DELAY)
      timers.current.push(t)
    },
    [live],
  )

  /**
   * 미리 써 둔 설명이 없는 섹션은 목업처럼 안내 문단 하나를 보여 줘요.
   * (예: §3.4 — 실제로는 Claude가 그 섹션 본문을 읽고 풀어 써요)
   */
  const topic = state.topicKey
    ? (topics[state.topicKey] ?? state.liveTopic ?? fallbackTopic(state.topicKey, sections))
    : undefined

  return { state, topic, open, close, clearLog, minimize, restore, ask }
}

/**
 * 섹션 id를 설명 주제로 바꿔요.
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
      { p: '서버 없이 화면만 보는 모드라 이 섹션 설명은 미리 써 두지 않았어요. 서버에 연결되면 Claude가 이 섹션 본문을 읽고 풀어 써요.' },
    ],
    qs: [],
  }
}
