import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dashboardQuery, gitFeedQuery } from '@/api/inbox'
import type { DashboardPayload, GitFeed } from '@/api/inbox'
import { resourcesQuery } from '@/api/system'
import { useAckRun } from '@/api/runs'
import { sessionsQuery } from '@/api/agents'
import type { AgentSession } from '@/api/agents'
import { AgentAside, Lanes, laneOf } from '../agents/SessionLanes'
import type { Run } from '@/api/runs'
import { ErrorState, LoadingState } from '@/components'
import { duration, whenShort } from '@/lib/time'
import { AgentsGraph } from '../agents/AgentsGraph'
import { ScheduleView } from '../schedule/ScheduleView'
import { RunStatePill } from '../projects/RunsTab'
import { StartGuide } from './StartGuide'
import s from './Dashboard.module.css'

/** Dashboard — docs/v3/mockups/MissionControl.dc.html. Overview만 2단계에서 실제 데이터 */
export default function DashboardPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'overview'
  const pick = (v: string) => {
    const next = new URLSearchParams(params)
    next.set('view', v)
    setParams(next, { replace: true })
  }
  return <Overview view={view === 'agents' || view === 'schedule' ? view : 'overview'} onView={pick} />
}

function greeting(d: Date) {
  const h = d.getHours()
  if (h >= 5 && h < 11) return '좋은 아침이에요'
  if (h >= 11 && h < 18) return '좋은 오후예요'
  return '좋은 저녁이에요'
}

const runHref = (r: Run, extra = '') => `/projects/${encodeURIComponent(r.project)}?tab=work&run=${encodeURIComponent(r.id)}${extra}`

function Overview({ view, onView }: { view: 'overview' | 'agents' | 'schedule'; onView: (v: string) => void }) {
  const dash = useQuery(dashboardQuery())
  const git = useQuery(gitFeedQuery())
  const agents = useQuery(sessionsQuery())
  // 답 필요가 위로
  const sorted = [...(agents.data?.sessions ?? [])].sort(
    (a, b) => Number(b.pending.length > 0) - Number(a.pending.length > 0) || b.updatedAt - a.updatedAt,
  )
  const now = new Date()
  const date = now.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })

  return (
    <div className={s.page}>
      <aside aria-label="에이전트" className={s.aside}>
        <div className={s.asideTitle}>에이전트</div>
        <AgentAside sessions={sorted} />
      </aside>

      <main className={s.main}>
        <div className={s.head}>
          <div>
            <div className={s.date}>{date}</div>
            <h1 className={s.title}>{greeting(now)}</h1>
            {dash.data && <Summary d={dash.data} sessions={sorted} />}
          </div>
          <div className={s.headRight}>
            <div role="tablist" aria-label="대시보드 보기" className={s.views}>
              {[
                ['overview', 'Overview'],
                ['agents', 'Agents'],
                ['schedule', 'Schedule'],
              ].map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={id === view} className={s.view} onClick={() => onView(id)}>
                  {label}
                </button>
              ))}
            </div>
            <Link to="/projects?tab=work" className={s.headBtn}>
              새 실행
            </Link>
            <Link to={sorted[0] ? `/projects/${encodeURIComponent(sorted[0].project)}/ade?new=1` : '/projects'} className={s.headBtnGhost}>
              새 세션
            </Link>
          </div>
        </div>

        {dash.isPending && <LoadingState label="대시보드를 불러오는 중이에요" />}
        {dash.isError && <ErrorState error={dash.error} onRetry={() => dash.refetch()} />}
        {dash.data && view === 'agents' && (
          <AgentsGraph sessions={sorted} runs={dash.data.runs.running} finished={dash.data.runs.finishedToday} />
        )}
        {dash.data && view === 'schedule' && <ScheduleView running={dash.data.runs.running} />}
        {dash.data && view === 'overview' && (
          <>
            <StartGuide projects={dash.data.projects} />
            <CutBanner runs={dash.data.runs.cut} />
            <Stats d={dash.data} sessions={sorted} git={git.data} />
            <div className={s.columns}>
              <section aria-label="에이전트 진행 현황" className={s.lanes}>
                <Lanes sessions={sorted} />

                <div className={s.laneHead} aria-label="학습 실행">
                  <span aria-hidden="true" className={s.laneDot} data-tone="run" />
                  <h2 className={s.h2}>학습 실행</h2>
                  <span className={s.count}>{dash.data.runs.running.length}</span>
                  <span className={s.laneHint}>실행 중 · 오늘 끝난 것</span>
                </div>
                {dash.data.runs.running.length + dash.data.runs.finishedToday.length === 0 && (
                  <div className={s.empty}>오늘은 실행이 없어요. Projects › 세션 · 실행에서 시작해요.</div>
                )}
                {[...dash.data.runs.running, ...dash.data.runs.finishedToday].map((r) => (
                  <RunCard key={`${r.project}/${r.id}`} r={r} />
                ))}
              </section>
              <aside aria-label="Git과 자원" className={s.side}>
                <GitCards feed={git.data} failed={git.isError} />
                <Resources self={dash.data.self} />
              </aside>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

function Summary({ d, sessions }: { d: DashboardPayload; sessions: AgentSession[] }) {
  const parts: ReactNode[] = []
  const lanes = laneOf(sessions)
  parts.push(
    <span key="ask">
      답이 필요한 에이전트 <b>{lanes.ask.length}</b>
    </span>,
    <span key="work">
      작업 중 <b>{lanes.work.length}</b>
    </span>,
  )
  parts.push(
    <span key="run">
      학습 <b>{d.runs.running.length}</b> 실행 중
    </span>,
  )
  if (d.runs.cut.length) {
    parts.push(
      <span key="cut">
        끊긴 실행 <b>{d.runs.cut.length}</b>
      </span>,
    )
  }
  if (d.runs.failedToday) {
    parts.push(
      <span key="fail">
        오늘 실패 <b>{d.runs.failedToday}</b>
      </span>,
    )
  }
  return (
    <div className={s.summary}>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && ' · '}
          {p}
        </span>
      ))}
    </div>
  )
}

function CutBanner({ runs }: { runs: Run[] }) {
  const ack = useAckRun()
  if (runs.length === 0) return null
  const r = runs[0]
  const at = new Date((r.endedAt ?? r.startedAt) * 1000).toLocaleString('ko-KR', {
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  return (
    <div role="status" className={s.banner}>
      <span className={s.bannerTitle}>중간에 끊긴 실행 {runs.length}</span>
      <span className={s.bannerText}>
        {r.project} · {r.name || r.id} — {at} {r.reason}. 자동으로 다시 돌리지 않아요.
      </span>
      <Link to={runHref(r, `&rerun=${encodeURIComponent(r.id)}`)} className={s.bannerBtn}>
        이어서 실행…
      </Link>
      <button type="button" className={s.bannerGhost} onClick={() => ack.mutate({ project: r.project, id: r.id })}>
        확인
      </button>
    </div>
  )
}

function lastEpoch(r: Run): { value: string; unit: string; sub: string } | null {
  const last = r.metrics?.last
  if (!last) return null
  for (const key of ['epoch', 'step', 'iter', 'iteration']) {
    if (key in last) return { value: String(last[key]), unit: ` ${key}`, sub: r.metrics?.file ?? '' }
  }
  return null
}

function Stats({ d, sessions, git }: { d: DashboardPayload; sessions: AgentSession[]; git?: GitFeed }) {
  const run = d.runs.running[0]
  const prog = run ? lastEpoch(run) : null
  const lanes = laneOf(sessions)
  const oldest = sessions.flatMap((x) => x.pending).sort((a, b) => a.createdAt - b.createdAt)[0]
  const tiles = [
    {
      label: '에이전트',
      value: String(lanes.ask.length + lanes.work.length + lanes.done.length),
      sub: `작업 중 ${lanes.work.length} · 답 필요 ${lanes.ask.length} · 끝남 ${lanes.done.length}`,
      tone: 'default',
    },
    {
      label: '답이 필요해요',
      value: String(lanes.ask.length),
      sub: oldest ? `가장 오래된 것 ${whenShort(oldest.createdAt)}` : '기다리는 승인이 없어요',
      tone: lanes.ask.length ? 'attention' : 'default',
    },
    run
      ? {
          label: `${run.name || run.id} 학습 중`,
          value: prog?.value ?? duration(run.durationSec),
          unit: prog?.unit ?? '',
          sub: `${run.project} · ${prog ? `${duration(run.durationSec)} 째` : '지표 파일을 아직 못 찾았어요'}${d.runs.running.length > 1 ? ` · 외 ${d.runs.running.length - 1}개` : ''}`,
          tone: 'default',
        }
      : {
          label: '학습',
          value: '0',
          sub: `오늘 끝남 ${d.runs.finishedToday.length - d.runs.failedToday} · 실패 ${d.runs.failedToday}`,
          tone: 'default',
        },
    git?.prs.available
      ? {
          label: '열린 PR',
          value: String(git.prs.items.length),
          sub: summarizePrs(git.prs.items),
          tone: 'default',
        }
      : { label: '열린 PR', value: '—', sub: git ? 'gh가 없어서 못 읽어요' : '…', tone: 'muted' },
    git
      ? {
          label: '이번 주 머지',
          value: String(git.merges.week),
          sub: git.merges.items[0] ? `오늘 ${git.merges.today} · ${git.merges.items[0].main} ← ${git.merges.items[0].branch || '…'}` : '이번 주에는 없어요',
          tone: 'default',
        }
      : { label: '이번 주 머지', value: '—', sub: '…', tone: 'muted' },
  ]
  return (
    <div className={s.stats}>
      {tiles.map((t) => (
        <div key={t.label} className={s.stat}>
          <div className={s.statLabel}>{t.label}</div>
          <div className={s.statValue} data-tone={t.tone}>
            {t.value}
            {'unit' in t && t.unit && <span className={s.statUnit}>{t.unit}</span>}
          </div>
          <div className={s.statSub}>{t.sub}</div>
        </div>
      ))}
    </div>
  )
}

function RunCard({ r }: { r: Run }) {
  const last = r.metrics?.last ?? {}
  const shown = Object.entries(last).slice(0, 4)
  return (
    <article className={s.card} data-state={r.state}>
      <div className={s.cardTop}>
        <span className={s.cardProject}>{r.project}</span>
        <span className={s.cardMeta}>
          {r.cwd === '.' ? '루트' : r.cwd} · conda {r.env || '없이'} · {whenShort(r.startedAt)}
        </span>
        <RunStatePill run={r} />
      </div>
      <h3 className={s.cardTitle}>{r.name ? `${r.id} · ${r.name}` : r.id}</h3>
      <p className={s.cardCmd}>{r.command}</p>
      <div className={s.cardFoot}>
        <span>{duration(r.durationSec)}</span>
        {r.exitCode !== null && <span>종료코드 {r.exitCode}</span>}
        {shown.map(([k, v]) => (
          <span key={k} className={s.mono}>
            {k} {v}
          </span>
        ))}
        <Link to={runHref(r)} className={s.cardLink}>
          로그 보기
        </Link>
      </div>
    </article>
  )
}

function Bar({ label, pct, value, tone = 'neutral' }: { label: string; pct: number | null; value: string; tone?: 'accent' | 'attention' | 'neutral' }) {
  return (
    <div className={s.res}>
      <span className={s.resLabel}>{label}</span>
      <div className={s.resTrack}>
        <div className={s.resBar} data-tone={tone} style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }} />
      </div>
      <span className={s.resValue}>{value}</span>
    </div>
  )
}

function Resources({ self }: { self: DashboardPayload['self'] }) {
  const res = useQuery(resourcesQuery())
  const g = res.data?.gpu
  const dev = g?.devices[0]
  const h = res.data?.host
  const vramPct = dev?.memUsedMb && dev.memTotalMb ? (100 * dev.memUsedMb) / dev.memTotalMb : null
  return (
    <section className={s.sideCard}>
      <h2 className={s.h2}>
        자원 <span className={s.h2Sub}>· 화면을 볼 때만 5초마다</span>
      </h2>
      {res.isError && <div className={s.muted}>자원을 읽지 못했어요.</div>}
      {g && !g.available && <div className={s.muted}>GPU 조회 불가 · {g.reason}</div>}
      {dev && (
        <>
          <Bar label="GPU" pct={dev.utilPct ?? null} value={`${Math.round(dev.utilPct ?? 0)}%`} tone="accent" />
          <Bar
            label="VRAM"
            pct={vramPct}
            value={`${((dev.memUsedMb ?? 0) / 1024).toFixed(1)}/${Math.round((dev.memTotalMb ?? 0) / 1024)}G`}
            tone={vramPct !== null && vramPct >= 80 ? 'attention' : 'accent'}
          />
          <Bar label="온도" pct={dev.tempC ?? null} value={dev.tempC != null ? `${Math.round(dev.tempC)}°C` : '—'} />
        </>
      )}
      {h && (
        <>
          <Bar label="CPU" pct={h.cpuPct} value={h.cpuPct != null ? `${Math.round(h.cpuPct)}%` : '…'} />
          <Bar label="RAM" pct={h.memory.pct ?? null} value={`${h.memory.usedGb ?? '?'}/${Math.round(h.memory.totalGb ?? 0)}G`} />
          <Bar label="디스크" pct={h.disk.pct ?? null} value={`${Math.round(h.disk.freeGb ?? 0)}G 여유`} />
        </>
      )}
      {vramPct !== null && vramPct >= 80 && (
        <div className={s.warn}>VRAM이 거의 찼어요 — 새 실행은 메모리가 모자랄 수 있어요</div>
      )}
      <div className={s.selfLine}>
        lab.remote 서버 자신: CPU {self.cpuPct ?? '…'}% · RAM {self.rssMb ?? '?'}MB · GPU 0
      </div>
    </section>
  )
}

function summarizePrs(items: GitFeed['prs']['items']) {
  if (!items.length) return '열린 PR이 없어요'
  const count = (state: string) => items.filter((p) => p.state === state).length
  return [`리뷰 기다림 ${count('리뷰 기다림')}`, `변경 요청 ${count('변경 요청')}`].join(' · ')
}

/** 오른쪽 "열린 PR" · "최근 머지" — 목업 MissionControl */
function GitCards({ feed, failed }: { feed?: GitFeed; failed?: boolean }) {
  return (
    <>
      <section className={s.sideCard}>
        <h2 className={s.h2}>
          열린 PR {feed?.prs.available && <span className={s.muted}>{feed.prs.items.length}</span>}
        </h2>
        {!feed && <div className={s.muted}>{failed ? 'git 기록을 못 읽었어요.' : '불러오는 중이에요…'}</div>}
        {feed && !feed.prs.available && <div className={s.muted}>{feed.prs.reason}</div>}
        {feed?.prs.available && feed.prs.items.length === 0 && <div className={s.muted}>열린 PR이 없어요.</div>}
        {feed?.prs.items.map((pr) => (
          <a key={`${pr.project}#${pr.number}`} href={pr.url} target="_blank" rel="noreferrer" className={s.gitRow}>
            <span className={s.gitTop}>
              <span className={s.gitNum}>#{pr.number}</span>
              <span className={s.gitTitle}>{pr.title}</span>
            </span>
            <span className={s.gitMeta}>
              <span className={s.gitPill} data-state={pr.state}>
                {pr.state}
              </span>
              {pr.ci && <span>{pr.ci}</span>}
              <span className={s.gitBranch}>{pr.branch}</span>
            </span>
          </a>
        ))}
      </section>
      <section className={s.sideCard}>
        <h2 className={s.h2}>
          최근 머지 {feed && <span className={s.muted}>이번 주 {feed.merges.week} · 오늘 {feed.merges.today}</span>}
        </h2>
        {feed && feed.merges.items.length === 0 && <div className={s.muted}>이번 주에 main에 합친 게 없어요.</div>}
        {feed?.merges.items.map((m) => (
          <div key={`${m.project}${m.at}${m.title}`} className={s.gitRow}>
            <span className={s.gitTitle}>{m.branch || m.title}</span>
            <span className={s.gitMeta}>
              {m.project} · {m.main} ← {m.branch || '…'} · {whenShort(m.at)}
            </span>
          </div>
        ))}
      </section>
    </>
  )
}
