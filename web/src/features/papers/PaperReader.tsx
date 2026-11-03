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
} from '@/components'
import type { SegmentedItem } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { AiPanel } from './reader/AiPanel'
import type { AiTab } from './reader/AiPanel'
import { ALL_HIGHLIGHTS_ON } from './reader/highlightCategories'
import type { HighlightToggles } from './reader/highlightCategories'
import { OutlinePanel } from './reader/OutlinePanel'
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

  const [papers, reader, summaries] = useQueries({
    queries: [papersQuery(), paperReaderQuery(id), paperSummariesQuery()],
  })
  const setStatus = useSetReadStatus()

  const paper = papers.data?.find((p) => p.id === id)
  const summary = summaries.data?.[id]

  // 본문을 아직 안 붙여서 읽은 위치는 0이에요 (다음 단계에서 스크롤에 연결)
  const progress = 0

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
          <SegmentedControl
            items={sourceItems}
            value={source}
            onChange={setSource}
            label="원문 형식"
            // HTML이 없는 논문은 PDF만 써요 (docs/spec.md I-0)
            disabled={!data.hasHtml}
          />
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
            onJump={setActiveId}
            progress={progress}
            showPages={source === 'pdf'}
            toggles={toggles}
            onToggle={(c) => setToggles((prev) => ({ ...prev, [c]: !prev[c] }))}
          />
          <Resizer handle={outline.resizerProps} label="아웃라인 너비 조절" />

          <div className={s.center}>
            <div className={s.placeholder}>
              <span className={s.placeholderTitle}>
                {source === 'pdf' ? 'PDF 보기는 다음 단계예요' : 'HTML 보기는 다음 단계예요'}
              </span>
              <span className={s.placeholderText}>
                지금은 화면 틀만 있어요. 아웃라인에서 섹션을 고르면 오른쪽 위에 현재
                섹션이 바뀌고, 하이라이트를 켜고 끄면 점과 노트 탭이 함께 움직여요.
              </span>
              <span className={s.placeholderMeta}>
                {data.pageCount}쪽 · 하이라이트 {data.highlights.length}개 · 참고문헌{' '}
                {data.referenceTotal}개
              </span>
            </div>
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
            onJumpSection={setActiveId}
          />
          {ai.closed && (
            <CollapsedRail side="right" label="AI 패널 펼치기" onExpand={ai.toggle} />
          )}
        </div>
      </div>
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
