import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { paperGraphQuery } from '@/api/papers'
import { projectsQuery } from '@/api/projects'
import type { GraphEdgeKind, GraphNode } from '@/api/types'
import { Button, ErrorState, LoadingState, VisuallyHidden } from '@/components'
import { layoutGraph } from '@/lib/graphLayout'
import { VaultDialog } from './VaultDialog'
import s from './PaperGraph.module.css'

/** 연결 종류 — 목업 PaperGraph의 KIND */
const KINDS: Array<{ id: GraphEdgeKind; label: string; color: string; dash: string; w: number }> = [
  { id: 'cite', label: '인용', color: 'var(--text-dim)', dash: '0', w: 1.5 },
  { id: 'use', label: '프로젝트에서 사용', color: 'var(--accent)', dash: '0', w: 2.5 },
  { id: 'note', label: '내 메모 링크', color: 'var(--purple)', dash: '6 4', w: 2 },
]

/** 논문 분류는 많은 순으로 세 가지 색까지. 나머지는 마지막 색을 같이 써요 */
const PAPER_COLORS = ['var(--accent)', 'var(--info)', 'var(--text-muted)']
const PROJECT_COLOR = 'var(--text)'
const NOTE_COLOR = 'var(--purple)'

const BOX = { pad: 30, padRight: 170 }

/** 그래프 위 이름은 짧게 — "LoRA: Low-Rank …"는 "LoRA"로. 전체 이름은 오른쪽 칸에 */
function shortName(n: GraphNode) {
  if (n.kind !== 'paper') return n.name.length > 28 ? `${n.name.slice(0, 27)}…` : n.name
  const head = n.name.split(/:\s/)[0]
  const name = head.length <= 28 ? head : n.name
  return name.length > 28 ? `${name.slice(0, 27)}…` : name
}

/** 목업의 List / Graph 전환 — 라이브러리 제목 옆 */
export function PapersViewSwitch({ current }: { current: 'list' | 'graph' }) {
  return (
    <div role="group" aria-label="논문 보기" className={s.switch}>
      <Link to="/papers" aria-current={current === 'list' ? 'page' : undefined}>
        List
      </Link>
      <Link to="/papers?view=graph" aria-current={current === 'graph' ? 'page' : undefined}>
        Graph
      </Link>
    </div>
  )
}

export default function PaperGraph() {
  const graph = useQuery(paperGraphQuery())
  const projects = useQuery(projectsQuery())
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [on, setOn] = useState<Record<GraphEdgeKind, boolean>>({ cite: true, use: true, note: true })
  const [near, setNear] = useState(false)
  const [find, setFind] = useState('')
  const [vaultOpen, setVaultOpen] = useState(false)

  const nodes = useMemo(() => graph.data?.nodes ?? [], [graph.data])
  const edges = useMemo(() => graph.data?.edges ?? [], [graph.data])
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  // 노드 크기는 연결 수 (켜고 끄는 것과 상관없이 전체 기준)
  const degree = useMemo(() => {
    const d = new Map<string, number>()
    for (const e of edges) {
      d.set(e.from, (d.get(e.from) ?? 0) + 1)
      d.set(e.to, (d.get(e.to) ?? 0) + 1)
    }
    return d
  }, [edges])

  const categories = useMemo(() => {
    const c = new Map<string, number>()
    for (const n of nodes) if (n.kind === 'paper') c.set(n.category, (c.get(n.category) ?? 0) + 1)
    return [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name]) => name)
  }, [nodes])

  const colorOf = (n: GraphNode) => {
    if (n.kind === 'project') return PROJECT_COLOR
    if (n.kind === 'note') return NOTE_COLOR
    const i = categories.indexOf(n.category)
    return PAPER_COLORS[Math.min(Math.max(i, 0), PAPER_COLORS.length - 1)]
  }

  // 그래프 칸 너비에 맞춰 그려요 (노드가 많으면 더 넓게 — 그때는 가로로 스크롤)
  const wrap = useRef<HTMLElement | null>(null)
  const [room, setRoom] = useState(760)
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setRoom(Math.max(560, el.clientWidth - 24)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [graph.isSuccess])
  const size = useMemo(() => {
    const width = Math.max(room, Math.round(Math.sqrt(nodes.length) * 150))
    return { width, height: Math.max(560, Math.round(width * 0.72)) }
  }, [nodes.length, room])

  const pos = useMemo(
    () =>
      layoutGraph(
        nodes.map((n) => n.id),
        edges.map((e) => [e.from, e.to]),
        { ...size, ...BOX },
      ),
    [nodes, edges, size],
  )

  if (graph.isError) {
    return (
      <main className={s.main}>
        <ErrorState title="그래프를 불러오지 못했어요" error={graph.error} onRetry={() => void graph.refetch()} />
      </main>
    )
  }
  if (!graph.data) {
    return (
      <main className={s.main}>
        <LoadingState label="그래프를 그리는 중이에요…" />
      </main>
    )
  }

  // 선택: 주소의 ?node= → 없으면 연결이 가장 많은 논문
  const fallback = [...nodes].sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))[0]
  const sel = byId.get(params.get('node') ?? '') ?? fallback
  const pick = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('view', 'graph')
    next.set('node', id)
    setParams(next, { replace: true })
  }

  const visible = edges.filter((e) => on[e.kind])
  const neighbors = new Set<string>(sel ? [sel.id] : [])
  for (const e of visible) {
    if (e.from === sel?.id) neighbors.add(e.to)
    if (e.to === sel?.id) neighbors.add(e.from)
  }
  const q = find.trim().toLowerCase()
  const matches = q ? nodes.filter((n) => n.name.toLowerCase().includes(q) || n.meta.toLowerCase().includes(q)) : []
  const shownNodes = nodes.filter((n) => !near || neighbors.has(n.id))
  const shownEdges = visible.filter((e) => !near || (neighbors.has(e.from) && neighbors.has(e.to)))

  const links = sel
    ? visible
        .filter((e) => e.from === sel.id || e.to === sel.id)
        .map((e) => {
          const other = byId.get(e.from === sel.id ? e.to : e.from)
          const why = e.kind === 'cite' ? (e.from === sel.id ? '인용함' : '인용됨') : KINDS.find((k) => k.id === e.kind)!.label
          return other ? { other, why, kind: e.kind } : null
        })
        .filter((x): x is { other: GraphNode; why: string; kind: GraphEdgeKind } => x !== null)
    : []

  // "Claude에게 묻기"는 ADE 새 세션에 질문을 채워 두기만 해요 — 보내기는 사람이 눌러요
  const askProject =
    (sel?.kind === 'project' ? sel.name : '') ||
    links.find((l) => l.other.kind === 'project')?.other.name ||
    nodes.find((n) => n.kind === 'project')?.name ||
    projects.data?.projects.find((p) => p.exists)?.name ||
    ''
  const vault = graph.data.vault
  const askDraft = sel
    ? [
        `지식그래프에서 "${sel.name}" 노드와 이어진 것들 사이의 관계를 정리해 줘.`,
        sel.path ? `- ${sel.name} · ${vault}/${sel.path}` : `- ${sel.name}`,
        ...links.map((l) => `- ${l.other.name} (${l.why})${l.other.path ? ` · ${vault}/${l.other.path}` : ''}`),
        '',
        '논문 노트는 읽기만 하고 고치지 마.',
      ].join('\n')
    : ''

  const counts = {
    paper: nodes.filter((n) => n.kind === 'paper').length,
    project: nodes.filter((n) => n.kind === 'project').length,
    note: nodes.filter((n) => n.kind === 'note').length,
  }

  const legend = [
    ...categories.slice(0, 2).map((c, i) => ({ label: `논문 · ${c}`, color: PAPER_COLORS[i] })),
    ...(categories.length === 3
      ? [{ label: `논문 · ${categories[2]}`, color: PAPER_COLORS[2] }]
      : categories.length > 3
        ? [{ label: `논문 · 기타 ${categories.length - 2}개 분류`, color: PAPER_COLORS[2] }]
        : []),
  ]

  return (
    <>
      <aside aria-label="그래프 필터" className={s.filters}>
        <div className={s.findWrap}>
          <VisuallyHidden>
            <label htmlFor="kg-find">노드 검색</label>
          </VisuallyHidden>
          <input
            id="kg-find"
            type="text"
            value={find}
            onChange={(e) => setFind(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && matches[0]) {
                pick(matches[0].id)
                setFind('')
              }
            }}
            placeholder="논문 · 메모 · 프로젝트 검색"
            className={s.find}
          />
          {q && (
            <ul className={s.findList} aria-label="검색 결과">
              {matches.slice(0, 8).map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => {
                      pick(n.id)
                      setFind('')
                    }}
                  >
                    {n.name}
                  </button>
                </li>
              ))}
              {matches.length === 0 && <li className={s.findNone}>일치하는 노드가 없어요</li>}
            </ul>
          )}
        </div>

        <fieldset className={s.kinds}>
          <legend>연결 종류</legend>
          {KINDS.map((k) => (
            <button
              key={k.id}
              type="button"
              aria-pressed={on[k.id]}
              onClick={() => setOn((old) => ({ ...old, [k.id]: !old[k.id] }))}
              className={s.kind}
            >
              <span aria-hidden="true" className={s.check}>
                {on[k.id] ? '✓' : ''}
              </span>
              <svg aria-hidden="true" width="28" height="8">
                <line x1="0" y1="4" x2="28" y2="4" style={{ stroke: k.color }} strokeWidth="2" strokeDasharray={k.dash} />
              </svg>
              <span className={s.kindLabel}>{k.label}</span>
              <span className={s.kindCount}>{edges.filter((e) => e.kind === k.id).length}</span>
            </button>
          ))}
        </fieldset>

        <div className={s.legend}>
          <span className={s.legendTitle}>노드</span>
          {legend.map((l) => (
            <span key={l.label} className={s.legendRow}>
              <span aria-hidden="true" className={s.legendDot} style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
          <span className={s.legendRow}>
            <span aria-hidden="true" className={s.legendSquare} />
            프로젝트
          </span>
          <span className={s.legendRow}>
            <span aria-hidden="true" className={s.legendDiamond} />내 메모
          </span>
        </div>

        <p className={s.hint}>인용은 참고문헌에서, 메모 연결은 vault의 [[링크]]에서 가져와요. 노드가 클수록 연결이 많아요.</p>
        <button type="button" className={s.vault} onClick={() => setVaultOpen(true)} title={vault}>
          vault · <span className={s.mono}>{vault}</span>
        </button>
      </aside>

      <main className={s.main}>
        <div className={s.toolbar}>
          <h1 className={s.title}>Library</h1>
          <PapersViewSwitch current="graph" />
          <span className={s.counts}>
            논문 {counts.paper} · 프로젝트 {counts.project} · 메모 {counts.note}
          </span>
          <div role="group" aria-label="보기 범위" className={s.range}>
            <button type="button" aria-pressed={!near} onClick={() => setNear(false)}>
              전체
            </button>
            <button type="button" aria-pressed={near} onClick={() => setNear(true)} disabled={!sel}>
              선택한 노드 주변만
            </button>
          </div>
        </div>

        <section aria-label="그래프" className={s.canvasWrap} ref={wrap}>
          {nodes.length === 0 ? (
            <div className={s.empty}>
              <b>그래프에 표시할 항목이 아직 없어요</b>
              <span>
                vault의 Papers/ 폴더에 논문 노트(MD)를 넣으면 여기에 표시돼요. frontmatter의 cites가 인용, 메모의 [[링크]]가 메모
                연결이에요.
              </span>
              <Button variant="primary" size="md" onClick={() => setVaultOpen(true)}>
                vault 위치 설정
              </Button>
            </div>
          ) : (
            <div className={s.canvas} style={{ width: size.width, height: size.height }}>
              <svg aria-hidden="true" width={size.width} height={size.height} className={s.lines}>
                {shownEdges.map((e, i) => {
                  const a = pos[e.from]
                  const b = pos[e.to]
                  const k = KINDS.find((x) => x.id === e.kind)!
                  const touch = e.from === sel?.id || e.to === sel?.id
                  if (!a || !b) return null
                  return (
                    <line
                      key={i}
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      style={{ stroke: k.color }}
                      strokeWidth={touch ? k.w + 0.5 : k.w}
                      strokeDasharray={k.dash}
                      opacity={touch ? 1 : 0.3}
                    />
                  )
                })}
              </svg>
              {shownNodes.map((n) => {
                const p = pos[n.id]
                if (!p) return null
                const isSel = n.id === sel?.id
                const lit = q ? matches.includes(n) : neighbors.has(n.id)
                const dot = Math.min(20, 9 + (degree.get(n.id) ?? 0) * 1.6)
                const color = colorOf(n)
                const dotStyle: CSSProperties = {
                  width: n.kind === 'note' ? dot * 0.75 : dot,
                  height: n.kind === 'note' ? dot * 0.75 : dot,
                  background: color,
                  boxShadow: isSel ? `0 0 0 3px var(--bg), 0 0 0 5px ${color}` : undefined,
                }
                return (
                  <button
                    key={n.id}
                    type="button"
                    aria-pressed={isSel}
                    aria-label={`${n.name} 선택`}
                    onClick={() => pick(n.id)}
                    className={s.node}
                    data-lit={lit}
                    style={{ left: p.x - 11, top: p.y - 11 }}
                  >
                    <span aria-hidden="true" className={s.dotBox}>
                      <span className={s.dot} data-kind={n.kind} style={dotStyle} />
                    </span>
                    <span className={s.nodeLabel} data-kind={n.kind} data-sel={isSel} title={n.name}>
                      {shortName(n)}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </section>
      </main>

      <aside aria-label="선택한 노드" className={s.detail}>
        {sel ? (
          <>
            <div>
              <span className={s.kindPill} style={{ background: colorOf(sel) }}>
                {sel.kind === 'paper' ? `논문 · ${sel.category}` : sel.category}
              </span>
              <h2 className={s.selTitle}>{sel.name}</h2>
              <div className={s.selMeta}>{sel.meta}</div>
            </div>
            <div className={s.selActions}>
              {sel.kind === 'paper' && (
                <Button variant="primary" size="md" href={`/papers/${encodeURIComponent(sel.id)}`}>
                  리더에서 열기
                </Button>
              )}
              {sel.kind === 'project' && (
                <Button variant="primary" size="md" href={`/projects/${encodeURIComponent(sel.name)}`}>
                  프로젝트 열기
                </Button>
              )}
              <Button variant="outline" size="md" href="/papers">
                라이브러리
              </Button>
            </div>
            <div>
              <div className={s.linksTitle}>연결 {links.length}</div>
              <ul className={s.links}>
                {links.map((l, i) => (
                  <li key={i}>
                    <button type="button" onClick={() => pick(l.other.id)} className={s.linkName}>
                      {l.other.name}
                    </button>
                    <span className={s.why} data-kind={l.kind}>
                      {l.why}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className={s.ask}>
              <span className={s.askTitle}>연결된 논문 사이의 관계 묻기</span>
              <span className={s.askText}>
                ADE 새 세션에 질문을 미리 입력해요. 보내기를 누를 때만 Claude에게 전송돼요.
                {askProject && (
                  <>
                    {' '}
                    프로젝트: <b>{askProject}</b>
                  </>
                )}
              </span>
              <button
                type="button"
                className={s.askBtn}
                disabled={!askProject}
                onClick={() => navigate(`/projects/${encodeURIComponent(askProject)}/ade?draft=${encodeURIComponent(askDraft)}`)}
              >
                Claude에게 묻기
              </button>
              {!askProject && <span className={s.askText}>등록한 프로젝트가 있어야 물을 수 있어요 (ADE는 프로젝트 안에서 실행돼요).</span>}
            </div>
          </>
        ) : (
          <p className={s.selMeta}>노드를 선택하면 연결이 여기에 표시돼요.</p>
        )}
      </aside>

      <VaultDialog open={vaultOpen} onClose={() => setVaultOpen(false)} />
    </>
  )
}
