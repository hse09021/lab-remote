import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  dashboardQuery,
  eventsQuery,
  experimentsQuery,
  projectsQuery,
  usePauseLoop,
  useStopExperiment,
} from '@/api/experiments'
import type { Dashboard, EventEntry, Experiment } from '@/api/types'
import { ErrorState, LoadingState, Sheet, Toast } from '@/components'
import { useToast } from '@/lib/useToast'
import { LearningCurveChart } from '../experiments/LearningCurveChart'
import { experimentStatus } from '../experiments/experimentStatus'
import s from './Mobile.module.css'

type SheetKind = 'stop' | null

export function MobileExperiments() {
  const [projects, dashboard, experiments, events] = useQueries({
    queries: [projectsQuery(), dashboardQuery(), experimentsQuery(), eventsQuery()],
  })

  const toast = useToast(2600)
  const [sheet, setSheet] = useState<SheetKind>(null)
  const stopExp = useStopExperiment()
  const pauseLoop = usePauseLoop()

  if (dashboard.isPending || experiments.isPending) {
    return <LoadingState label="실험 상태를 불러오는 중이에요…" />
  }
  if (dashboard.isError || !dashboard.data || !experiments.data) {
    return (
      <ErrorState
        title="실험 상태를 불러오지 못했어요"
        error={dashboard.error}
        onRetry={() => void dashboard.refetch()}
      />
    )
  }

  const d: Dashboard = dashboard.data
  const list: Experiment[] = experiments.data
  const running = list.find((e) => e.state === 'running')

  return (
    <div className={s.page}>
      {/* 프로젝트 */}
      <div className={s.controlRow}>
        <span className={s.project}>{projects.data?.projects[0]?.name ?? d.project}</span>
        <span className={s.loop}>{d.loopPaused ? '루프 멈춤' : d.loopLabel}</span>
      </div>

      {/* 승인 대기 */}
      {d.approval && (
        <section className={`${s.card} ${s.approval}`} aria-label="승인 대기">
          <span className={s.approvalTitle}>승인 대기 {d.approval.count}</span>
          <p className={s.approvalText}>{d.approval.text}</p>
          <a href={d.approval.ctaHref} target="_blank" rel="noopener" className={s.approvalCta}>
            {d.approval.ctaLabel}
          </a>
        </section>
      )}

      {/* 진행 중인 실험 */}
      {running && (
        <section className={s.card} aria-label={`${running.id} 진행`}>
          <div className={s.runHead}>
            <span className={s.runId}>{running.id}</span>
            <span data-tone={experimentStatus(running).tone} className={s.badge}>
              {experimentStatus(running).label}
            </span>
          </div>
          <span className={s.runKnob}>{running.knob}</span>
          <div className={s.runMeta}>
            <span className={s.runEpoch}>
              {d.metrics[0]?.value}
              <span className={s.runEpochSuffix}>{d.metrics[0]?.valueSuffix} epoch</span>
            </span>
            <span className={s.runSub}>{d.metrics[0]?.sub}</span>
          </div>
          {/* 대시보드와 같은 컴포넌트 · 크기만 모바일용 */}
          <LearningCurveChart curve={d.learningCurve} size="mobile" />
        </section>
      )}

      {/* 지표 4칸 */}
      <div className={s.metricGrid}>
        {d.metrics.slice(1, 5).map((m) => (
          <div key={m.label} className={s.metric}>
            <span className={s.metricLabel}>{m.label}</span>
            <span className={s.metricValue}>{m.value}</span>
            <span className={s.metricSub}>{m.sub}</span>
          </div>
        ))}
      </div>

      {/* 큐 · 최근 결과 */}
      <section className={s.card} aria-label="큐 · 최근 결과">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>큐 · 최근 결과</span>
          <span className={s.cardNote}>GPU 1개 · 순차 실행</span>
        </div>
        <ul className={s.queue}>
          {list.map((e) => (
            <li key={e.id} className={s.queueRow}>
              <div className={s.queueMain}>
                <span className={s.queueId}>{e.id}</span>
                <span className={s.queueKnob}>{e.knob}</span>
              </div>
              <span className={s.queueAcc}>{e.bestAcc ?? '—'}</span>
              <span data-tone={experimentStatus(e).tone} className={s.badge}>
                {experimentStatus(e).label}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* 결정 · 이벤트 */}
      <section className={s.card} aria-label="결정·이벤트">
        <div className={s.cardHead}>
          <span className={s.cardTitle}>결정·이벤트</span>
          <span className={s.cardNote}>Decision_log.md</span>
        </div>
        <ul className={s.events}>
          {(events.data ?? []).map((e: EventEntry, i) => (
            <li key={`${e.time}-${i}`} className={s.eventRow}>
              <span className={s.eventTime}>{e.time}</span>
              <div className={s.eventBody}>
                <span data-tone={e.tone} className={s.eventTag}>
                  {e.kind}
                </span>
                <span className={s.eventText}>{e.text}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* 조작 */}
      <div className={s.actions}>
        <button
          type="button"
          onClick={() => {
            const next = !d.loopPaused
            pauseLoop.mutate(next)
            toast.show(next ? '루프를 일시정지했어요' : '루프를 다시 시작했어요')
          }}
          className={s.actionBtn}
        >
          {d.loopPaused ? '루프 다시 시작' : '루프 일시정지'}
        </button>
        <button
          type="button"
          disabled={!running}
          onClick={() => setSheet('stop')}
          className={`${s.actionBtn} ${s.danger}`}
        >
          {running ? `${running.id} 정지` : '정지할 실험 없음'}
        </button>
      </div>
      <p className={s.footNote}>완료·이상 감지·에러·사용량 알림은 Discord로 와요</p>

      {/* 정지 확인 시트 */}
      <Sheet
        open={sheet === 'stop'}
        title={running ? `${running.id} 정지할까요?` : '정지'}
        onClose={() => setSheet(null)}
      >
        <p className={s.sheetText}>
          마지막 체크포인트를 저장하고 학습을 멈춰요. 큐에 있는 실험은 그대로 남고, 루프는
          일시정지돼요.
        </p>
        <div className={s.sheetButtons}>
          <button type="button" onClick={() => setSheet(null)} className={s.sheetCancel}>
            취소
          </button>
          <button
            type="button"
            onClick={() => {
              if (running) stopExp.mutate(running.id)
              setSheet(null)
              toast.show('정지 요청을 보냈어요 · 체크포인트를 저장해요')
            }}
            className={s.sheetDanger}
          >
            정지하기
          </button>
        </div>
      </Sheet>

      <Toast message={toast.message} placement="bottom" />
    </div>
  )
}
