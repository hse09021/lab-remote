import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  dashboardQuery,
  eventsQuery,
  experimentsQuery,
  projectsQuery,
} from '@/api/experiments'
import type { Dashboard, EventEntry, Experiment } from '@/api/types'
import type { Column } from '@/components'
import {
  Banner,
  Button,
  CollapsedRail,
  DataTable,
  ErrorState,
  LoadingState,
  MetricTile,
  MetricTileRow,
  Pill,
  Resizer,
  SectionHeader,
  Skeleton,
  SplitButton,
} from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { CurveLegend, LearningCurveChart } from './LearningCurveChart'
import { ProjectSidebar } from './ProjectSidebar'
import { ResourceMeterList } from './ResourceMeterList'
import { experimentStatus } from './experimentStatus'
import s from './ExperimentDashboard.module.css'

/** 비어 있는 칸은 목업처럼 em 대시로 */
const BLANK = '—'

export default function ExperimentDashboard() {
  const nav = usePaneResize({
    initial: 250,
    min: 200,
    max: 400,
    dir: 1,
    collapsible: true,
  })

  const [projects, dashboard, experiments, events] = useQueries({
    queries: [projectsQuery(), dashboardQuery(), experimentsQuery(), eventsQuery()],
  })

  return (
    <>
      {nav.closed && (
        <CollapsedRail side="left" label="사이드바 펼치기" onExpand={nav.toggle} />
      )}
      <ProjectSidebar
        style={nav.style}
        onCollapse={nav.toggle}
        data={projects.data}
        isError={projects.isError}
      />
      <Resizer handle={nav.resizerProps} label="실험 메뉴 너비 조절" />

      <main id="overview" className={s.main}>
        <DashboardHeader data={dashboard.data} isError={dashboard.isError} />

        {dashboard.isError ? (
          <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
        ) : dashboard.data ? (
          <DashboardBody data={dashboard.data} />
        ) : (
          <LoadingState label="대시보드를 불러오는 중이에요…" />
        )}

        <ExperimentTable
          caption={dashboard.data?.queueCaption ?? ''}
          rows={experiments.data}
          isError={experiments.isError}
          error={experiments.error}
          onRetry={() => void experiments.refetch()}
        />

        <EventLog
          caption={dashboard.data?.eventsCaption ?? ''}
          rows={events.data}
          isError={events.isError}
          error={events.error}
          onRetry={() => void events.refetch()}
        />
      </main>
    </>
  )
}

/* ── 머리말 ───────────────────────────────────────────────── */

function DashboardHeader({
  data,
  isError,
}: {
  data: Dashboard | undefined
  isError: boolean
}) {
  return (
    <div className={s.headerRow}>
      <div className={s.titleBlock}>
        {data ? (
          <h1 className={s.title}>{data.project}</h1>
        ) : isError ? (
          // 못 불러왔으면 스켈레톤을 계속 깜빡이지 않고 화면 이름만 둬요.
          // 자세한 사정은 아래 안내가 설명해요.
          <h1 className={s.titleFallback}>실험</h1>
        ) : (
          <Skeleton width={280} height={34} />
        )}
        <div className={s.chips}>
          {data ? (
            <>
              <Pill tone="success">{data.modeLabel}</Pill>
              <Pill tone="neutral">{data.loopLabel}</Pill>
            </>
          ) : isError ? null : (
            <Skeleton width={200} height={22} />
          )}
        </div>
      </div>

      <div className={s.actions}>
        <Button>루프 일시정지</Button>
        <SplitButton
          label="새 실험"
          menuLabel="새 실험"
          items={[
            { label: 'Claude와 토론하며 설계' },
            {
              label: '논문에서 재현 실험 만들기',
              to: '/experiments/new/from-paper',
            },
            { label: '설정만 바꿔 큐에 추가' },
          ]}
        />
      </div>
    </div>
  )
}

/* ── 승인 대기 · 지표 · 차트 ──────────────────────────────── */

function DashboardBody({ data }: { data: Dashboard }) {
  return (
    <>
      {data.approval && (
        <Banner
          label="승인 대기"
          badge={`승인 대기 ${data.approval.count}`}
          action={
            <Button
              variant="attention"
              size="md"
              href={data.approval.ctaHref}
              target="_blank"
              rel="noopener"
            >
              {data.approval.ctaLabel}
            </Button>
          }
        >
          {data.approval.text}
        </Banner>
      )}

      <MetricTileRow label="요약 지표">
        {data.metrics.map((tile) => (
          <MetricTile key={tile.label} tile={tile} />
        ))}
      </MetricTileRow>

      <div className={s.chartsRow}>
        <section aria-label="학습 곡선" className={s.curveSection}>
          <div className={s.curveHead}>
            <h2 className={s.curveTitle}>{data.learningCurve.title}</h2>
            <CurveLegend kind="train">Train loss</CurveLegend>
            <CurveLegend kind="val">Val loss</CurveLegend>
            <a href={data.learningCurve.wandbHref} className={s.wandb}>
              W&amp;B에서 열기
            </a>
          </div>
          <LearningCurveChart curve={data.learningCurve} />
        </section>

        <section aria-label="자원" className={s.resourceSection}>
          <h2 className={s.resourceTitle}>자원</h2>
          <ResourceMeterList rows={data.resources} />
        </section>
      </div>
    </>
  )
}

/* ── 실험 · 큐 ────────────────────────────────────────────── */

const COLUMNS: Column<Experiment>[] = [
  {
    key: 'id',
    label: '실험',
    render: (e) => <span className={s.expId}>{e.id}</span>,
  },
  {
    key: 'knob',
    label: '조작변인',
    render: (e) => (
      <>
        {e.knob}
        {e.knobNote && <span className={s.knobNote}> {e.knobNote}</span>}
      </>
    ),
  },
  {
    key: 'state',
    label: '상태',
    render: (e) => {
      const st = experimentStatus(e)
      return (
        <Pill tone={st.tone} variant="status">
          {st.label}
        </Pill>
      )
    },
  },
  {
    key: 'bestAcc',
    label: 'Best val acc',
    align: 'right',
    render: (e) =>
      e.bestAcc ? (
        <span className={s.bestAcc}>{e.bestAcc}</span>
      ) : (
        <span className={s.blank}>{BLANK}</span>
      ),
  },
  {
    key: 'branch',
    label: '브랜치 · 커밋',
    cellClassName: s.commitCell,
    render: (e) =>
      e.branch && e.commit ? (
        `${e.branch} · ${e.commit}`
      ) : (
        <span className={s.blank}>{BLANK}</span>
      ),
  },
  {
    key: 'report',
    label: '분석',
    render: (e) =>
      e.report ? (
        <Link to="/code">{e.report}</Link>
      ) : (
        <span className={s.blank}>{BLANK}</span>
      ),
  },
]

function ExperimentTable({
  caption,
  rows,
  isError,
  error,
  onRetry,
}: {
  caption: string
  rows: Experiment[] | undefined
  isError: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <section id="experiments" aria-label="실험과 큐" className={s.tableSection}>
      <SectionHeader title="실험 · 큐" aside={caption} />
      {isError ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : rows ? (
        <DataTable
          label="실험과 큐"
          columns={COLUMNS}
          rows={rows}
          rowKey={(e) => e.id}
          rowTinted={(e) => e.state === 'running'}
        />
      ) : (
        <LoadingState label="실험 목록을 불러오는 중이에요…" />
      )}
    </section>
  )
}

/* ── 결정·이벤트 기록 ─────────────────────────────────────── */

function EventLog({
  caption,
  rows,
  isError,
  error,
  onRetry,
}: {
  caption: string
  rows: EventEntry[] | undefined
  isError: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <section id="events" aria-label="결정과 이벤트" className={s.eventsSection}>
      <SectionHeader title="결정·이벤트 기록" aside={caption} asideMono className={s.eventsHead} />
      {isError ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : rows ? (
        rows.map((e) => (
          <div key={`${e.time}-${e.kind}`} className={s.eventRow}>
            <span className={s.eventTime}>{e.time}</span>
            <span data-tone={e.tone} className={s.eventKind}>
              {e.kind}
            </span>
            <span className={s.eventText}>{e.text}</span>
          </div>
        ))
      ) : (
        <LoadingState label="기록을 불러오는 중이에요…" />
      )}
    </section>
  )
}
