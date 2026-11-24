import { useEffect, useRef, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { ApiError, isMockMode } from '@/api/client'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  paperReaderQuery,
  paperSummariesQuery,
  paperPdfHref,
  papersQuery,
  notesQuery,
  useMakeSummary,
  askIsLive,
  runReaderAi,
  useStartAnalysis,
  useFetchPaperHtml,
  useFetchPaperPdf,
  usePaperHtmlState,
  refPaperId,
  summaryDraftsQuery,
  useSaveReference,
  useSaveSummaryMd,
  useSetReadStatus,
} from '@/api/papers'
import type { PaperSource, ReadStatus } from '@/api/types'
import {
  Button,
  CollapsedRail,
  ErrorState,
  LoadingState,
  Resizer,
  SegmentedControl,
  StatusPill,
  Toast,
} from '@/components'
import type { SegmentedItem } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { useToast } from '@/lib/useToast'
import { AiPanel } from './reader/AiPanel'
import { useVaultReader } from './reader/vaultReader'
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
import { useIsMobile } from '@/lib/useMediaQuery'
import { MobilePapers } from '../mobile/MobilePapers'

/**
 * 휴대폰이면 목록 + 요약 시트, 아니면 리더.
 * 둘을 다른 컴포넌트로 나눠요 — 한 컴포넌트에서 훅 앞에 돌려주면, 창 폭이 바뀌는 순간
 * 훅 개수가 달라져 화면이 깨져요 (React #300).
 */
export default function PaperReader() {
  const isMobile = useIsMobile()
  return isMobile ? <MobilePapers /> : <DesktopReader />
}

function DesktopReader() {
  const { id = 'attn' } = useParams<{ id: string }>()
  // `?section=`으로 들어오면 그 섹션부터 보여 줘요
  const [search] = useSearchParams()
  const wantSection = search.get('section')

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
  // 보던 섹션 — 처음에는 없어요 (스크롤하면 본문이 알려 줘요)
  const [activeId, setActiveId] = useState<string | null>(null)
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
  const navigate = useNavigate()
  const overlays = useReaderOverlays()
  /** 마우스가 올라간 설명 대상 — E 키로 열어요 */
  const hovered = useRef<{ key: string; anchor: SelectionAnchor } | null>(null)
  /** 대화창 본체는 스크롤과 무관하게 가운데 열 모서리에 붙어요 */
  const centerRef = useRef<HTMLDivElement | null>(null)

  const requestJump = (target: JumpTarget) =>
    setJump((prev) => ({ target, nonce: (prev?.nonce ?? 0) + 1 }))

  /* ?section= 으로 들어왔으면 본문이 준비된 뒤 한 번만 이동해요 */
  const jumpedTo = useRef<string | null>(null)
  useEffect(() => {
    if (!wantSection || jumpedTo.current === wantSection) return
    jumpedTo.current = wantSection
    setActiveId(wantSection)
    setJump((prev) => ({
      target: { sectionId: wantSection },
      nonce: (prev?.nonce ?? 0) + 1,
    }))
  }, [wantSection])

  const [papers, reader, summaries, mdDrafts, annotations] = useQueries({
    queries: [
      papersQuery(),
      // 미리 만든 리더 데이터는 목업 논문뿐이라, 서버에 붙어 있으면 아예 묻지 않아요
      { ...paperReaderQuery(id), enabled: isMockMode() },
      paperSummariesQuery(),
      summaryDraftsQuery(),
      annotationsQuery(id),
    ],
  })
  const setStatus = useSetReadStatus()
  const notes = useQuery(notesQuery())
  const makeSummary = useMakeSummary()
  const saveRef = useSaveReference()
  const saveMd = useSaveSummaryMd()
  const addAnn = useAddAnnotation(id)
  const updateAnn = useUpdateAnnotation(id)
  const removeAnn = useRemoveAnnotation(id)
  const restoreAnn = useRestoreAnnotation(id)
  const paper = papers.data?.find((p) => p.id === id)
  const vault = useVaultReader(
    id,
    paper,
    !isMockMode() || (reader.isError && reader.error instanceof ApiError && reader.error.status === 404),
  )
  // vault 논문 — 미리 써 둔 설명이 없어서 서버에 물어요 (누를 때만)
  const aiLive = askIsLive() && !reader.data && !!vault.data
  const chat = useFloatingChat(
    (reader.data ?? vault.data)?.topics ?? {},
    (reader.data ?? vault.data)?.sections ?? [],
    aiLive ? { paperId: id } : null,
  )
  const startAnalysis = useStartAnalysis(id)
  // vault의 arXiv 논문 — HTML 본문은 데이터 폴더에 받아 둬요 (안 받았으면 누를 때)
  const fetchHtml = useFetchPaperHtml()
  const fetchPdf = useFetchPaperPdf()
  const vaultHtml = !reader.data && !!paper?.arxiv
  const htmlNeeded = vaultHtml && source === 'arxiv-html' && paper?.htmlState !== 'done'
  const htmlQ = usePaperHtmlState(id, htmlNeeded)
  const htmlState = htmlNeeded ? (htmlQ.data?.state ?? paper?.htmlState ?? 'missing') : 'done'
  const [liveTr, setLiveTr] = useState<{ text: string; translation: string | null; note: string | null } | null>(null)

  /*
   * 단축키는 훅이라 조기 반환보다 앞에 있어야 해요.
   * 핸들러는 렌더마다 바뀌니 ref로 최신 것을 읽어요.
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

  /*
   * 바깥을 누르면 떠 있는 것들을 닫아요.
   * 메뉴 항목을 누를 때는 닫히면 안 되니, 떠 있는 것 안쪽은 지나쳐요.
   * (누르는 순간 닫고 click으로 동작하면 핸들러가 안 돌아요)
   */
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null
      if (el?.closest('[data-reader-overlay]')) return
      overlays.closeAll()
      setMyMenu(null)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [overlays])

  const summary = summaries.data?.[id]

  const sourceItems: SegmentedItem<PaperSource>[] = [
    { value: 'arxiv-html', label: 'arXiv HTML' },
    { value: 'pdf', label: 'PDF' },
  ]

  // vault에서 온 논문 — 미리 만든 리더 데이터가 없어요. PDF가 있으면 PDF로 같은 리더 화면을 그리고,
  // PDF도 없으면 노트만 보여 줘요
  const missing = !isMockMode() || (reader.isError && reader.error instanceof ApiError && reader.error.status === 404)
  if (missing && paper && vault.active && !vault.failed) {
    if (!vault.data) {
      return (
        <main className={s.page}>
          <LoadingState label="PDF를 여는 중이에요…" />
        </main>
      )
    }
  } else if (missing && paper) {
    return (
      <main className={s.page}>
        <div className={s.noteOnly}>
          <Link to="/papers" className={s.noteBack}>
            ← 라이브러리
          </Link>
          <span className={s.noteHead}>
            <h1 className={s.noteTitle}>{paper.title}</h1>
            <Link to={`/papers?view=graph&node=${encodeURIComponent(id)}`} className={s.graphLink}>
              그래프에서 보기
            </Link>
          </span>
          <div className={s.metaRow}>
            <span>
              {paper.authors}
              {paper.venue && ` · ${paper.venue}`}
            </span>
            <StatusPill
              status={paper.status}
              size="md"
              label={`${paper.title} 읽음 상태`}
              onChange={(status: ReadStatus) => setStatus.mutate({ id, status })}
            />
          </div>
          <p className={s.noteHint}>
            PDF가 없어서 vault 노트({paper.path})만 보여요.
            {paper.arxiv ? ' arXiv에서 PDF를 받으면 리더로 열려요. PDF는 데이터 폴더에 저장하고, 노트는 수정하지 않아요.' : ' 라이브러리에서 PDF를 올리면 리더로 열려요.'}
          </p>
          {paper.arxiv && (
            <div className={s.noteActions}>
              <Button variant="primary" size="md" disabled={fetchPdf.isPending} onClick={() => fetchPdf.mutate(id)}>
                {fetchPdf.isPending ? 'arXiv에서 받는 중…' : 'arXiv에서 PDF 받기'}
              </Button>
              {fetchPdf.error && <span className={s.noteHint}>{fetchPdf.error instanceof Error ? fetchPdf.error.message : String(fetchPdf.error)}</span>}
            </div>
          )}
          {paper.hasPdf && (
            <a href={paperPdfHref(id)} target="_blank" rel="noreferrer" className={s.graphLink}>
              PDF 열기 (새 탭)
            </a>
          )}
          {notes.data?.[id] ? <pre className={s.noteBody}>{notes.data[id]}</pre> : <p className={s.noteHint}>노트 본문이 비어 있어요.</p>}
        </div>
      </main>
    )
  }

  if (reader.isError && !vault.data) {
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

  const data = reader.data ?? vault.data
  if (!data) {
    return (
      <main className={s.page}>
        <LoadingState label="논문을 불러오는 중이에요…" />
      </main>
    )
  }

  /* ── 떠 있는 것들 공통 핸들러 ─────────────────────────── */
  const openChat = (key: string, anchor: SelectionAnchor, context: string | null = null) => {
    overlays.closeAll()
    // 그림 · 표 · 수식 — 캡션이나 식 글자를 맥락으로 같이 보내요
    const label = key.replace(/^el:\d+:/, '')
    const spot =
      key.startsWith('el:') && context === null
        ? (data.explainSpots?.find((x) => x.key === key) ?? data.explainSpots?.find((x) => x.label === label))
        : undefined
    // HTML 보기에서 누른 것(쪽 모름)은 PDF에서 찾은 같은 이름의 쪽으로 — 같은 대화로 이어져요
    const samePdf = key.startsWith('el:0:') ? data.explainSpots?.find((x) => x.label === label) : undefined
    chat.open(topicKeyFor(samePdf?.key ?? key, data.topics), anchor, spot ? spot.text : context)
  }
  const openCite = (n: number, anchor: SelectionAnchor) => overlays.openCite(n, anchor)
  const onHover = (key: string | null, anchor: SelectionAnchor | null) => {
    hovered.current = key && anchor ? { key, anchor } : null
  }

  /** 위치 표기. 번호가 없는 섹션(Abstract·References)은 § 을 붙이지 않아요 */
  // 새 메모 · 주석 자리 — 보던 섹션이 이 논문에 없으면(목차 없는 PDF 등) 첫 섹션
  const hereId = activeId && data.sections.some((x) => x.id === activeId) ? activeId : (data.sections[0]?.id ?? '')
  const sectionLabel = (sectionId: string) => {
    const sec = data.sections.find((x) => x.id === sectionId)
    if (!sec) return sectionId
    return `${sec.n ? `§${sec.n}` : sec.title} · p.${sec.page}`
  }

  const onSelectionAct = (a: SelectionAction) => {
    const sel = overlays.selection
    if (!sel) return
    switch (a) {
      // vault 논문은 고른 글을 맥락으로 넘겨 서버가 그 구절을 풀어요
      case 'explain':
        openChat('lstm', sel.anchor, aiLive ? sel.text : null)
        break
      case 'info':
        openChat('info', sel.anchor, aiLive ? sel.text : null)
        break
      case 'ask':
        openChat('ask', sel.anchor, aiLive ? sel.text : null)
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
          toast.show('하이라이트를 추가했어요 · 노트 탭에서 볼 수 있어요')
        }
        break
      }
      case 'translate':
        overlays.openPopover('translate', sel.anchor, sel.text, sel.sectionId, sel.place)
        if (aiLive) {
          const text = sel.text
          setLiveTr({ text, translation: null, note: null })
          runReaderAi<{ translation: string; note: string }>(id, { kind: 'translate', text, page: sel.place.page })
            .then((r) => setLiveTr((p) => (p?.text === text ? { text, translation: r.translation, note: r.note || null } : p)))
            .catch((e: unknown) =>
              setLiveTr((p) => (p?.text === text ? { text, translation: `번역하지 못했어요 — ${e instanceof Error ? e.message : String(e)}`, note: null } : p)),
            )
        }
        break
      case 'note':
        overlays.openPopover('note', sel.anchor, sel.text, sel.sectionId, sel.place)
        break
    }
  }

  actions.current = { selection: onSelectionAct, explain: openChat }

  /** 보관 여부는 라이브러리 캐시가 단일 출처예요 — /papers 목록과 늘 같아요 */
  // 실제 API에서는 arXiv 번호나 제목이 같은 논문이 vault에 있으면 보관된 것으로 봐요
  const savedPaper = (r: { n: number; arxiv: string | null; title?: string }) =>
    (papers.data ?? []).find(
      (p) =>
        p.id === refPaperId(r) ||
        (!!r.arxiv && p.arxiv === r.arxiv) ||
        (!!r.title && p.title.trim().toLowerCase() === r.title.trim().toLowerCase()),
    )
  const isRefSaved = (r: { n: number; arxiv: string | null; title?: string }) => !!savedPaper(r)

  const myAnnotations = annotations.data ?? []
  const myHighlights = myAnnotations.filter((a) => a.kind === 'highlight')
  const myNotes = myAnnotations.filter((a) => a.kind === 'note')
  const myHighlightFor = (text: string) => myHighlights.find((a) => a.text === text)

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
      liveTranslation={liveTr}
      chatHost={centerRef}
      chat={chat}
      overlays={overlays}
      reader={data}
      onSelectionAct={onSelectionAct}
      onJump={(sectionId) => {
        setActiveId(sectionId)
        requestJump({ sectionId })
      }}
      onOpenPaper={(title) => {
        // 라이브러리에 있으면 그 논문 리더로, 없으면 라이브러리 검색으로
        const t = title.trim().toLowerCase()
        const hit = papers.data?.find((p) => p.title.trim().toLowerCase() === t)
          ?? papers.data?.find((p) => p.title.toLowerCase().includes(t) || t.includes(p.title.toLowerCase()))
        if (hit) navigate(`/papers/${encodeURIComponent(hit.id)}`)
        else toast.show(`${title} — 라이브러리에 없어요`)
      }}
      onSaveNote={(body) => {
        const pop = overlays.popover
        const sid = pop?.sectionId ?? hereId
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
        saveRef.mutate(
          { reference, save, savedId: savedPaper(reference)?.id },
          { onError: (e) => toast.show(e instanceof Error ? e.message : String(e)) },
        )
        toast.show(save ? '라이브러리에 보관했어요' : '보관을 취소했어요 · 휴지통에서 되돌릴 수 있어요')
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
            <span className={s.titleLine}>
              <h1 className={s.title}>{data.title}</h1>
              <Link to={`/papers?view=graph&node=${encodeURIComponent(id)}`} className={s.graphLink}>
                그래프에서 보기
              </Link>
            </span>
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
                if (next === 'arxiv-html' && vaultHtml && paper?.htmlState !== 'done' && paper?.htmlState !== 'running') {
                  fetchHtml.mutate(id)
                }
                if (activeId) requestJump({ sectionId: activeId })
              }}
              label="원문 형식"
              disabled={!data.hasHtml}
            />
          </span>
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
                aiLive={aiLive}
                reader={data}
                toggles={toggles}
                jump={jump}
                onActiveSection={setActiveId}
                onProgress={setProgress}
                onAskChat={(sectionId, page) => {
                  setTab('chat')
                  ai.setOpen(true)
                  toast.show(`${sectionLabel(sectionId)}에 대해 묻는 채팅 탭을 열었어요`)
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
                myNotes={myNotes}
                onMyHighlight={(annotation, anchor) =>
                  setMyMenu({ annotation, anchor })
                }
                onHover={onHover}
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
            ) : htmlState !== 'done' ? (
              <div className={s.htmlWait}>
                {htmlState === 'none' ? (
                  <p>arXiv에 이 논문의 HTML 본문이 없어요. PDF로 읽어 주세요.</p>
                ) : htmlState === 'error' || fetchHtml.isError ? (
                  <>
                    <p>arXiv HTML을 받지 못했어요.</p>
                    <Button variant="outline" size="md" onClick={() => fetchHtml.mutate(id)}>
                      다시 받기
                    </Button>
                  </>
                ) : (
                  <p>arXiv HTML 본문과 그림을 받는 중이에요… 처음 한 번만 받으면 다음부터 바로 열려요.</p>
                )}
                <Button variant="outline" size="md" onClick={() => setSource('pdf')}>
                  PDF로 보기
                </Button>
              </div>
            ) : (
              <HtmlView
                reader={data}
                toggles={toggles}
                // 이동 요청의 대상을 그대로 넘겨요 (없으면 보던 섹션)
                jump={
                  jump?.target.sectionId || jump?.target.highlightId
                    ? { sectionId: jump.target.sectionId ?? '', highlightId: jump.target.highlightId, nonce: jump.nonce }
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
            onMakeSummary={
              askIsLive() && paper
                ? () => makeSummary.mutate(id, { onError: (e) => toast.show(e instanceof Error ? e.message : String(e)) })
                : undefined
            }
            summaryRunning={paper?.summaryState === 'running' || makeSummary.isPending}
            onAnalyze={aiLive ? () => startAnalysis.mutate(undefined, { onError: (e) => toast.show(e instanceof Error ? e.message : String(e)) }) : undefined}
            analyzing={vault.analyzing || startAnalysis.isPending}
            analyzed={!!vault.analysis}
            chatPaperId={aiLive ? id : undefined}
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
              toast.show('주석을 수정했어요')
            }}
            onDeleteNote={deleteAnnotation}
            currentLabel={hereId ? sectionLabel(hereId) : ''}
            onAddNote={(text) => {
              const sid = hereId
              addAnn.mutate({
                kind: 'note',
                text,
                source: '',
                sectionId: sid,
                page: data.sections.find((x) => x.id === sid)?.page ?? 1,
                anchor: null,
                boxes: null,
              })
              toast.show('메모를 남겼어요')
            }}
            onJumpSection={(sectionId) => {
              setActiveId(sectionId)
              requestJump({ sectionId })
            }}
            onJumpHighlight={(h) => {
              if (h.section) setActiveId(h.section)
              // PDF는 그 줄 조금 위로, HTML은 그 구절로
              const top = h.boxes[0]?.[1]
              requestJump({ sectionId: h.section || undefined, page: h.page, y: top !== undefined ? Math.max(0, top - 60) : undefined, highlightId: h.id })
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
