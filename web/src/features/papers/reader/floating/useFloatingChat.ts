import { useCallback, useRef, useState } from 'react'
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
  /** 메모 카드에서 열었을 때 붙는 맥락 */
  context: string | null
}

const EMPTY: FloatingChatState = {
  open: false,
  minimized: false,
  topicKey: null,
  anchor: null,
  log: [],
  asked: {},
  context: null,
}

/** 목업처럼 답이 조금 늦게 와요 */
const ANSWER_DELAY = 900

export function useFloatingChat(topics: Record<string, Topic>, sections: PaperSection[] = []) {
  const [state, setState] = useState<FloatingChatState>(EMPTY)
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([])

  const open = useCallback(
    (topicKey: string, anchor: ChatAnchor | null, context: string | null = null) => {
      setState({
        open: true,
        minimized: false,
        topicKey,
        anchor,
        log: [],
        asked: {},
        context,
      })
    },
    [],
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
    [],
  )

  /**
   * 미리 써 둔 설명이 없는 섹션은 목업처럼 안내 문단 하나를 보여 줘요.
   * (예: §3.4 — 실제로는 Claude 가 그 섹션 본문을 읽고 풀어 써요)
   */
  const topic = state.topicKey
    ? (topics[state.topicKey] ?? fallbackTopic(state.topicKey, sections))
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
