import { useEffect, useRef, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  paperReaderQuery,
  paperSummariesQuery,
  papersQuery,
  refPaperId,
  summaryDraftsQuery,
  useChooseDiscrepancy,
  useSaveReference,
  useSaveSummaryMd,
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
import {
  annotationsQuery,
  useAddAnnotation,
  useRemoveAnnotation,
  useRestoreAnnotation,
  useUpdateAnnotation,
} from '@/api/annotations'
import type { UserAnnotation } from '@/api/annotations'
import { FloatingLayer } from './reader/floating/FloatingLayer'
import type { SelectionAction, SelectionAnchor } from './reader/floating/SelectionMenu'
import { SELECTION_KEYS } from './reader/floating/SelectionMenu'
import { useFloatingChat, topicKeyFor } from './reader/floating/useFloatingChat'
import { useReaderOverlays } from './reader/floating/useReaderOverlays'
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
  /** 아직 저장 전인 수정 중 글 (저장하면 저장소로 가요) */
  const [mdEdit, setMdEdit] = useState<string | null>(null)
  const [toggles, setToggles] = useState<HighlightToggles>(ALL_HIGHLIGHTS_ON)
  const [progress, setProgress] = useState(0)
  const [jump, setJump] = useState<{ target: JumpTarget; nonce: number } | null>(null)
  const [nudgeDismissed, setNudgeDismissed] = useState(false)
  /** 채팅 탭에 붙는 맥락 칩 */
  const [chatContext, setChatContext] = useState<string | null>(null)
  /** 본문에서 내 하이라이트를 누르면 뜨는 작은 메뉴 */
  const [myMenu, setMyMenu] = useState<{
    annotation: UserAnnotation
    anchor: SelectionAnchor
  } | null>(null)

  const toast = useToast()
  const overlays = useReaderOverlays()
  /** 마우스가 올라간 설명 대상 — E 키로 열어요 */
  const hovered = useRef<{ key: string; anchor: SelectionAnchor } | null>(null)
  /** 대화창 본체는 스크롤과 무관하게 가운데 열 모서리에 붙어요 */
  const centerRef = useRef<HTMLDivElement | null>(null)

  const requestJump = (target: JumpTarget) =>
    setJump((prev) => ({ target, nonce: (prev?.nonce ?? 0) + 1 }))

  const [papers, reader, summaries, mdDrafts, annotations] = useQueries({
    queries: [
      papersQuery(),
      paperReaderQuery(id),
      paperSummariesQuery(),
      summaryDraftsQuery(),
      annotationsQuery(id),
    ],
  })
  const setStatus = useSetReadStatus()
  const saveRef = useSaveReference()
  const saveMd = useSaveSummaryMd()
  const chooseTarget = useChooseDiscrepancy(id)
  const addAnn = useAddAnnotation(id)
  const updateAnn = useUpdateAnnotation(id)
  const removeAnn = useRemoveAnnotation(id)
  const restoreAnn = useRestoreAnnotation(id)
  const chat = useFloatingChat(reader.data?.topics ?? {}, reader.data?.sections ?? [])

  /*
   * 단축키는 훅이라 조기 반환보다 앞에 있어야 해요.
   * 핸들러는 렌더마다 바뀌니 ref 로 최신 것을 읽어요.
   */
  const actions = useRef<{
    selection: (a: SelectionAction) => void
    explain: (key: string, anchor: SelectionAnchor) => void
  } | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && /^(INPUT|TEXTAREA)$/.test(el.tagName)) return

      if (e.key === 'Escape') {
        overlays.closeAll()
        setMyMenu(null)
        return
      }
      if (overlays.selection) {
        const act = SELECTION_KEYS[e.key.toLowerCase()]
        if (act) {
          e.preventDefault()
          actions.current?.selection(act)
        }
        return
      }
      // 설명 버튼·그림·수식에 마우스를 올린 상태에서 E
      if (e.key.toLowerCase() === 'e' && hovered.current) {
        e.preventDefault()
        actions.current?.explain(hovered.current.key, hovered.current.anchor)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlays])

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

  /* ── 떠 있는 것들 공통 핸들러 ─────────────────────────── */
  const openChat = (key: string, anchor: SelectionAnchor, context: string | null = null) => {
    overlays.closeAll()
    chat.open(topicKeyFor(key, data.topics), anchor, context)
  }
  const openCite = (n: number, anchor: SelectionAnchor) => overlays.openCite(n, anchor)
  const onHover = (key: string | null, anchor: SelectionAnchor | null) => {
    hovered.current = key && anchor ? { key, anchor } : null
  }

  /** 위치 표기. 번호가 없는 섹션(Abstract·References)은 § 을 붙이지 않아요 */
  const sectionLabel = (sectionId: string) => {
    const sec = data.sections.find((x) => x.id === sectionId)
    if (!sec) return sectionId
    return `${sec.n ? `§${sec.n}` : sec.title} · p.${sec.page}`
  }

  const onSelectionAct = (a: SelectionAction) => {
    const sel = overlays.selection
    if (!sel) return
    switch (a) {
      case 'explain':
        openChat('lstm', sel.anchor)
        break
      case 'info':
        openChat('info', sel.anchor)
        break
      case 'ask':
        openChat('ask', sel.anchor)
        break
      case 'highlight': {
        const mine = myHighlightFor(sel.text)
        overlays.closeAll()
        if (mine) {
          removeAnn.mutate(mine.id)
          toast.show('하이라이트를 지웠어요')
        } else {
          addAnn.mutate({
            kind: 'highlight',
            text: sel.text,
            source: sel.text,
            sectionId: sel.sectionId,
            page: sel.place.page,
            anchor: sel.place.anchor,
            boxes: sel.place.boxes,
          })
          toast.show('하이라이트했어요 · 노트에 모아 둘게요')
        }
        break
      }
      case 'translate':
        overlays.openPopover('translate', sel.anchor, sel.text, sel.sectionId)
        break
      case 'note':
        overlays.openPopover('note', sel.anchor, sel.text, sel.sectionId)
        break
    }
  }

  actions.current = { selection: onSelectionAct, explain: openChat }

  /** 보관 여부는 라이브러리 캐시가 단일 출처예요 — /papers 목록과 늘 같아요 */
  const isRefSaved = (r: { n: number; arxiv: string | null }) =>
    (papers.data ?? []).some((p) => p.id === refPaperId(r))

  const myAnnotations = annotations.data ?? []
  const myHighlights = myAnnotations.filter((a) => a.kind === 'highlight')
  const myHighlightFor = (text: string) => myHighlights.find((a) => a.text === text)

  /** PDF 선택 흉내 핫스팟에 얹는 표식 (목업과 같은 3가지) */
  const spotText = data.selectionSpot.text
  const selectionMarks = {
    active: overlays.selection?.text === spotText || overlays.popover?.text === spotText,
    // 내 하이라이트는 MyPdfHighlights 가 그려요. 여기서는 겹쳐 칠하지 않아요
    highlighted: false,
    annotated: myAnnotations.some((a) => a.kind === 'note' && a.source === spotText),
  }

  /** 노트 탭에서 지울 때 — 5초 안에 되돌릴 수 있어요 */
  const deleteAnnotation = (a: UserAnnotation) => {
    removeAnn.mutate(a.id)
    toast.show(a.kind === 'highlight' ? '하이라이트를 삭제했어요' : '주석을 삭제했어요', {
      durationMs: 5000,
      action: {
        label: '되돌리기',
        onAct: () => {
          restoreAnn.mutate(a)
          toast.clear()
        },
      },
    })
  }

  const floating = (
    <FloatingLayer
      chatHost={centerRef}
      chat={chat}
      overlays={overlays}
      reader={data}
      onSelectionAct={onSelectionAct}
      onJump={(sectionId) => {
        setActiveId(sectionId)
        requestJump({ sectionId })
      }}
      onOpenPaper={(title) => toast.show(`${title} — 라이브러리에서 열어요`)}
      onSaveNote={(body) => {
        const pop = overlays.popover
        const sid = pop?.sectionId ?? activeId ?? data.sections[0].id
        addAnn.mutate({
          kind: 'note',
          text: body,
          source: pop?.text ?? data.selectionSpot.text,
          sectionId: sid,
          page: pop?.place?.page ?? data.sections.find((x) => x.id === sid)?.page ?? 1,
          anchor: pop?.place?.anchor ?? null,
          boxes: pop?.place?.boxes ?? null,
        })
        overlays.setPopover(null)
        toast.show('주석을 남겼어요 · 노트 탭에서 볼 수 있어요')
      }}
      isRefSaved={isRefSaved}
      isMine={(text) => !!myHighlightFor(text)}
      myMenu={myMenu}
      onMyMenuAnnotate={() => {
        if (!myMenu) return
        const a = myMenu.annotation
        overlays.openPopover('note', myMenu.anchor, a.text, a.sectionId, {
          page: a.page,
          anchor: a.anchor,
          boxes: a.boxes,
        })
        setMyMenu(null)
      }}
      onMyMenuDelete={() => {
        if (!myMenu) return
        deleteAnnotation(myMenu.annotation)
        setMyMenu(null)
      }}
      onMyMenuClose={() => setMyMenu(null)}
      onSaveRef={(n) => {
        const reference = data.references.find((r) => r.n === n)
        if (!reference) return
        const save = !isRefSaved(reference)
        saveRef.mutate({ reference, save })
        toast.show(save ? '라이브러리에 보관했어요 · 요약 대기열에 넣었어요' : '보관을 취소했어요')
      }}
      onWorth={(n) => {
        const anchor = overlays.cite?.anchor
        if (anchor) {
          overlays.closeAll()
          chat.open('ask', anchor, `참고문헌 ${n}번`)
        }
      }}
      onToast={toast.show}
    />
  )

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

          <div ref={centerRef} className={s.center}>
            {source === 'pdf' ? (
              <PdfView
                reader={data}
                toggles={toggles}
                jump={jump}
                onActiveSection={setActiveId}
                onProgress={setProgress}
                onAskChat={(sectionId, page) => {
                  setTab('chat')
                  ai.setOpen(true)
                  toast.show(`${sectionLabel(sectionId)} 를 맥락으로 채팅 탭을 열었어요`)
                  setChatContext(`§${
                    data.sections.find((x) => x.id === sectionId)?.n || sectionId
                  } · p.${page}`)
                }}
                onOpenHtml={(sectionId) => {
                  setSource('arxiv-html')
                  setActiveId(sectionId)
                }}
                onExplain={openChat}
                onCite={openCite}
                onSelect={(anchor, text, sectionId, place) =>
                  overlays.openSelection(anchor, text, sectionId, place)
                }
                myHighlights={myHighlights}
                onMyHighlight={(annotation, anchor) =>
                  setMyMenu({ annotation, anchor })
                }
                onHover={onHover}
                selectionMarks={selectionMarks}
                floating={floating}
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
                onExplain={openChat}
                onCite={openCite}
                onSelect={(anchor, text, sectionId, place) =>
                  overlays.openSelection(anchor, text, sectionId, place)
                }
                myHighlights={myHighlights}
                onMyHighlight={(annotation, anchor) =>
                  setMyMenu({ annotation, anchor })
                }
                onHover={onHover}
                floating={floating}
                onToast={toast.show}
                target={data.discrepancy.chosen}
                onTargetChange={(v) => {
                  chooseTarget.mutate(v)
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
            isRefSaved={isRefSaved}
            reader={data}
            summary={summary}
            summaryView={summaryView}
            onSummaryViewChange={setSummaryView}
            mdDraft={mdEdit ?? mdDrafts.data?.[id] ?? null}
            mdSaved={mdDrafts.data?.[id] ?? null}
            onMdDraftChange={setMdEdit}
            onMdSave={() => {
              const markdown = mdEdit ?? mdDrafts.data?.[id]
              if (markdown !== undefined) saveMd.mutate({ id, markdown })
              setMdEdit(null)
            }}
            toggles={toggles}
            chatContext={chatContext}
            userNotes={myAnnotations}
            sectionLabel={sectionLabel}
            onEditNote={(a, text) => {
              updateAnn.mutate({ id: a.id, text })
              toast.show('주석을 고쳤어요')
            }}
            onDeleteNote={deleteAnnotation}
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

      <Toast message={toast.message} action={toast.action} />
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
