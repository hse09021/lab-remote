import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  paperReaderQuery,
  paperSummariesQuery,
  papersQuery,
  useSetReadStatus,
} from '@/api/papers'
import type { PaperSource, ReadStatus } from '@/api/types'
import {
  CollapsedRail,
  ErrorState,
  LoadingState,
  Resizer,
  SegmentedControl,
  SplitButton,
  StatusPill,
  Toast,
} from '@/components'
import type { SegmentedItem } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { useToast } from '@/lib/useToast'
import { AiPanel } from './reader/AiPanel'
import type { AiTab } from './reader/AiPanel'
import { ALL_HIGHLIGHTS_ON } from './reader/highlightCategories'
import type { HighlightToggles } from './reader/highlightCategories'
import { OutlinePanel } from './reader/OutlinePanel'
import { PdfView } from './reader/PdfView'
import type { JumpTarget } from './reader/PdfView'
import { HtmlView } from './reader/html/HtmlView'
import type { SummaryView } from './PaperSummaryPane'
import s from './PaperReader.module.css'

export default function PaperReader() {
  const { id = 'attn' } = useParams<{ id: string }>()

  const outline = usePaneResize({
    initial: 270,
    min: 200,
    max: 420,
    dir: 1,
    collapsible: true,
  })
  const ai = usePaneResize({
    initial: 400,
    min: 300,
    max: 640,
    dir: -1,
    collapsible: true,
  })

  const [source, setSource] = useState<PaperSource>('pdf')
  const [activeId, setActiveId] = useState<string | null>('abs')
  const [tab, setTab] = useState<AiTab>('summary')
  const [summaryView, setSummaryView] = useState<SummaryView>('nice')
  const [mdDraft, setMdDraft] = useState<string | null>(null)
  const [toggles, setToggles] = useState<HighlightToggles>(ALL_HIGHLIGHTS_ON)
  const [progress, setProgress] = useState(0)
  const [jump, setJump] = useState<{ target: JumpTarget; nonce: number } | null>(null)
  const [nudgeDismissed, setNudgeDismissed] = useState(false)
  // 수치 불일치에서 고른 재현 기준 (요약 MD 에도 남겨요)
  const [target, setTarget] = useState<string | null>(null)

  const toast = useToast()

  const requestJump = (target: JumpTarget) =>
    setJump((prev) => ({ target, nonce: (prev?.nonce ?? 0) + 1 }))

  const [papers, reader, summaries] = useQueries({
    queries: [papersQuery(), paperReaderQuery(id), paperSummariesQuery()],
  })
  const setStatus = useSetReadStatus()

  const paper = papers.data?.find((p) => p.id === id)
  const summary = summaries.data?.[id]

  const sourceItems: SegmentedItem<PaperSource>[] = [
    { value: 'arxiv-html', label: 'arXiv HTML' },
    { value: 'pdf', label: 'PDF' },
  ]

  if (reader.isError) {
    return (
      <main className={s.page}>
        <ErrorState
          title="논문을 불러오지 못했어요"
          error={reader.error}
          onRetry={() => void reader.refetch()}
        />
      </main>
    )
  }

  if (!reader.data) {
    return (
      <main className={s.page}>
        <LoadingState label="논문을 불러오는 중이에요…" />
      </main>
    )
  }

  const data = reader.data
  // 끝까지 읽었고 아직 완료가 아니면 물어봐요 (docs/HANDOFF.md 공통 동작)
  const showNudge = !nudgeDismissed && progress >= 97 && paper?.status !== 'done'

  return (
    <div className={s.page}>
      <div className={s.toolbar}>
        <div className={s.left}>
          <Link to="/papers" aria-label="라이브러리로 돌아가기" className={s.back}>
            <ChevronLeft />
          </Link>
          <div className={s.titleBlock}>
            <h1 className={s.title}>{data.title}</h1>
            <div className={s.metaRow}>
              <span>
                {data.meta} · <span className={s.mono}>{data.arxivId}</span>
              </span>
              {paper && (
                <StatusPill
                  status={paper.status}
                  size="md"
                  label={`${data.title} 읽음 상태`}
                  onChange={(status: ReadStatus) => setStatus.mutate({ id, status })}
                />
              )}
              <span aria-hidden="true">·</span>
              <span>
                읽은 위치 <span className={s.mono}>{progress}%</span>
              </span>
            </div>
          </div>
        </div>

        <div className={s.right}>
          <a
            href={data.arxivUrl}
            target="_blank"
            rel="noopener"
            className={s.external}
          >
            arXiv에서 열기 <ExternalIcon />
          </a>
          <span
            // HTML이 없는 논문은 PDF만 써요 (docs/spec.md I-0)
            title={data.hasHtml ? undefined : 'HTML 없음 · PDF로 읽어요'}
          >
            <SegmentedControl
              items={sourceItems}
              value={source}
              onChange={(next) => {
                // 읽던 섹션을 그대로 두고 형식만 바꿔요
                setSource(next)
                if (activeId) requestJump({ sectionId: activeId })
              }}
              label="원문 형식"
              disabled={!data.hasHtml}
            />
          </span>
          <SplitButton
            label="실험 설계 초안"
            menuLabel="실험 설계 초안"
            items={[{ label: '논문에서 재현 실험 만들기', to: '/experiments/new/from-paper' }]}
          />
        </div>
      </div>

      <div className={s.workspaceScroll}>
        <div className={s.workspace}>
          {outline.closed && (
            <CollapsedRail side="left" label="아웃라인 펼치기" onExpand={outline.toggle} />
          )}
          <OutlinePanel
            style={outline.style}
            onCollapse={outline.toggle}
            sections={data.sections}
            highlights={data.highlights}
            activeId={activeId}
            onJump={(sectionId) => {
              setActiveId(sectionId)
              requestJump({ sectionId })
            }}
            progress={progress}
            showPages={source === 'pdf'}
            toggles={toggles}
            onToggle={(c) => setToggles((prev) => ({ ...prev, [c]: !prev[c] }))}
          />
          <Resizer handle={outline.resizerProps} label="아웃라인 너비 조절" />

          <div className={s.center}>
            {source === 'pdf' ? (
              <PdfView
                reader={data}
                toggles={toggles}
                jump={jump}
                onActiveSection={setActiveId}
                onProgress={setProgress}
                onAskChat={() => {
                  setTab('chat')
                  ai.setOpen(true)
                }}
                onOpenHtml={(sectionId) => {
                  setSource('arxiv-html')
                  setActiveId(sectionId)
                }}
                onExplain={() => toast.show('섹션 설명은 다음 단계에서 붙여요')}
                onToast={toast.show}
                nudge={{
                  show: showNudge,
                  onMarkDone: () => {
                    setStatus.mutate({ id, status: 'done' })
                    setNudgeDismissed(true)
                  },
                  onDismiss: () => setNudgeDismissed(true),
                }}
              />
            ) : (
              <HtmlView
                reader={data}
                toggles={toggles}
                // 이동 요청의 대상을 그대로 넘겨요 (없으면 보던 섹션)
                jump={
                  jump?.target.sectionId
                    ? { sectionId: jump.target.sectionId, nonce: jump.nonce }
                    : activeId
                      ? { sectionId: activeId, nonce: 0 }
                      : null
                }
                onActiveSection={setActiveId}
                onProgress={setProgress}
                onExplain={() => toast.show('섹션 설명은 다음 단계에서 붙여요')}
                onCite={(n) => toast.show(`참고문헌 ${n}번 카드는 다음 단계에서 붙여요`)}
                onToast={toast.show}
                target={target}
                onTargetChange={(v) => {
                  setTarget(v)
                  toast.show(`재현 목표를 ${v}로 정했어요 · 요약 MD에도 남겼어요`)
                }}
                nudge={{
                  show: showNudge,
                  onMarkDone: () => {
                    setStatus.mutate({ id, status: 'done' })
                    setNudgeDismissed(true)
                  },
                  onDismiss: () => setNudgeDismissed(true),
                }}
              />
            )}
          </div>

          <Resizer handle={ai.resizerProps} label="AI 패널 너비 조절" />
          <AiPanel
            style={ai.style}
            onCollapse={ai.toggle}
            tab={tab}
            onTabChange={setTab}
            reader={data}
            summary={summary}
            summaryView={summaryView}
            onSummaryViewChange={setSummaryView}
            mdDraft={mdDraft}
            onMdDraftChange={setMdDraft}
            onMdSave={() => setMdDraft(null)}
            toggles={toggles}
            onJumpSection={(sectionId) => {
              setActiveId(sectionId)
              requestJump({ sectionId })
            }}
          />
          {ai.closed && (
            <CollapsedRail side="right" label="AI 패널 펼치기" onExpand={ai.toggle} />
          )}
        </div>
      </div>

      <Toast message={toast.message} />
    </div>
  )
}

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

const ChevronLeft = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M15 6l-6 6 6 6" />
  </svg>
)
const ExternalIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" />
  </svg>
)
