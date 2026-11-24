import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentSession } from '@/api/agents'
import type { Run } from '@/api/runs'
import s from './Graph.module.css'

/**
 * Dashboard › Agents — 프로젝트별 상자, You, 세션 · 하위 에이전트 · 학습 실행 노드.
 * 실선 = 부모와 하위 에이전트, 점선 = 서로 참고(같은 worktree의 세션과 실행),
 * 주황 점선 = 나를 기다리는 요청. 노드를 누르면 그 세션이나 실행으로 가요.
 */

type Kind = 'ask' | 'work' | 'run' | 'done'
interface Node {
  key: string
  x: number
  y: number
  title: string
  state: string
  kind: Kind
  href: string
  isRun: boolean
}
interface Edge {
  from: string
  to: string
  style: 'you' | 'ask' | 'child' | 'ref'
}

const COL = 230
const ROW = 110
const BOX_PAD = 70
const YOU = { x: 60, y: 0 }

const DAY = 24 * 3600

function stateOf(x: AgentSession): Kind {
  if (x.pending.length) return 'ask'
  if (x.state === 'working') return 'work'
  return 'done'
}

export function AgentsGraph({ sessions, runs, finished }: { sessions: AgentSession[]; runs: Run[]; finished: Run[] }) {
  const [showDone, setShowDone] = useState(false)
  const now = Date.now() / 1000
  const visible = sessions.filter((x) => stateOf(x) !== 'done' || (showDone && now - x.updatedAt < DAY))
  const runList = [...runs, ...(showDone ? finished : [])]
  const projects = [...new Set([...visible.map((x) => x.project), ...runList.map((r) => r.project)])]

  const nodes: Node[] = []
  const edges: Edge[] = []
  const boxes: { name: string; x: number; y: number; w: number; h: number }[] = []
  let left = 160
  for (const p of projects) {
    const ss = visible.filter((x) => x.project === p)
    const rr = runList.filter((r) => r.project === p)
    let row = 0
    let cols = 1
    for (const x of ss) {
      const k = stateOf(x)
      const key = `s:${x.id}`
      nodes.push({
        key,
        x: left + BOX_PAD,
        y: 70 + row * ROW,
        title: x.title,
        state: k === 'ask' ? `답 필요 · ${x.pending[0]?.tool ?? ''}` : k === 'work' ? (x.todos?.current ? `작업 중 · ${x.todos.current}` : '작업 중') : '끝남',
        kind: k,
        href: `/projects/${encodeURIComponent(x.project)}/ade?session=${x.id}`,
        isRun: false,
      })
      edges.push({ from: 'you', to: key, style: k === 'ask' ? 'ask' : 'you' })
      const subs = (x.subagents ?? []).filter((t) => showDone || t.status === 'running')
      subs.forEach((t, i) => {
        const sk = `t:${x.id}:${t.taskId}`
        nodes.push({
          key: sk,
          x: left + BOX_PAD + COL,
          y: 70 + (row + i) * ROW,
          title: t.description || '하위 에이전트',
          state: t.status === 'running' ? '작업 중 · 하위' : `하위 · ${t.status}`,
          kind: t.status === 'running' ? 'work' : 'done',
          href: `/projects/${encodeURIComponent(x.project)}/ade?session=${x.id}`,
          isRun: false,
        })
        edges.push({ from: key, to: sk, style: 'child' })
        cols = 2
      })
      row += Math.max(1, subs.length)
    }
    for (const r of rr) {
      const key = `r:${p}:${r.id}`
      nodes.push({
        key,
        x: left + BOX_PAD,
        y: 70 + row * ROW,
        title: `${r.id}${r.name ? ` · ${r.name}` : ''} 학습`,
        state: r.state === 'running' ? '실행 중' : r.stateLabel,
        kind: r.state === 'running' ? 'run' : 'done',
        href: `/projects/${encodeURIComponent(p)}?tab=work&run=${r.id}`,
        isRun: true,
      })
      // 같은 worktree에서 도는 세션과는 "참고" 점선
      for (const x of ss) {
        if ((x.tree === '.' ? '.' : x.tree) === (r.cwd || '.')) edges.push({ from: `s:${x.id}`, to: key, style: 'ref' })
      }
      edges.push({ from: 'you', to: key, style: 'you' })
      row += 1
    }
    const w = BOX_PAD * 2 + (cols - 1) * COL + 40
    boxes.push({ name: p, x: left, y: 10, w, h: 70 + Math.max(1, row) * ROW - 20 })
    left += w + 30
  }
  const height = Math.max(320, ...boxes.map((b) => b.y + b.h + 20))
  const width = Math.max(600, left)
  const you = { ...YOU, y: height / 2 }
  const at = (k: string) => (k === 'you' ? you : nodes.find((n) => n.key === k)!)

  const counts = {
    ask: sessions.filter((x) => stateOf(x) === 'ask').length,
    work: sessions.filter((x) => stateOf(x) === 'work').length,
    run: runs.length,
    done: sessions.filter((x) => stateOf(x) === 'done' && now - x.updatedAt < DAY).length + finished.length,
  }

  return (
    <section aria-label="에이전트 관계" className={s.wrap}>
      <div className={s.head}>
        <div className={s.legend}>
          {(
            [
              ['ask', `Needs you ${counts.ask}`],
              ['work', `Working ${counts.work}`],
              ['run', `Running ${counts.run}`],
              ['done', `Done ${counts.done}`],
            ] as [Kind, string][]
          ).map(([k, label]) => (
            <span key={k} className={s.legendItem}>
              <span className={s.legendDot} data-kind={k} />
              {label}
            </span>
          ))}
        </div>
        <button type="button" role="checkbox" aria-checked={showDone} className={s.check} onClick={() => setShowDone(!showDone)}>
          <span className={s.box} data-on={showDone}>
            {showDone ? '✓' : ''}
          </span>
          오늘 끝난 것도 보기
        </button>
      </div>

      <div className={s.canvasWrap}>
        <div className={s.canvas} style={{ width, height }}>
          {boxes.map((b) => (
            <div key={b.name} className={s.box2} style={{ left: b.x, top: b.y, width: b.w, height: b.h }}>
              <span className={s.boxName}>{b.name}</span>
            </div>
          ))}
          <svg className={s.svg} width={width} height={height} aria-hidden="true">
            {edges.map((e, i) => {
              const a = at(e.from)
              const b = at(e.to)
              return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={s.edge} data-style={e.style} />
            })}
          </svg>
          <div className={s.you} style={{ left: you.x - 28, top: you.y - 28 }} aria-label="나 (You)">
            You
          </div>
          {nodes.map((n) => (
            <Link key={n.key} to={n.href} className={s.node} style={{ left: n.x - 100, top: n.y - 24 }} data-kind={n.kind} aria-label={`${n.title}, ${n.state}`}>
              <span className={s.circle} data-kind={n.kind}>
                {n.isRun ? '▶' : ''}
              </span>
              <span className={s.card}>
                <span className={s.title}>{n.title}</span>
                <span className={s.state} data-kind={n.kind}>
                  {n.state}
                </span>
              </span>
            </Link>
          ))}
          {nodes.length === 0 && <div className={s.empty}>지금 돌고 있는 세션이나 학습이 없어요. "오늘 끝난 것도 보기"로 오늘 것을 볼 수 있어요.</div>}
        </div>
      </div>
      <p className={s.note}>
        lab.remote로 띄운 세션, 하위 에이전트, 학습 실행만 보여요. 실선은 부모와 하위 에이전트 사이, 점선은 서로 참고하는 관계(같은 worktree), 주황
        점선은 나를 기다리는 요청이에요. 노드를 누르면 그 세션이나 실행으로 가요.
      </p>
    </section>
  )
}
