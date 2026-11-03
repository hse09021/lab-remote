import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ExplainZone, Highlight, PaperReaderPayload } from '@/api/types'
import type { ReactNode } from 'react'
import { Button, IconButton } from '@/components'
import { copyText } from '@/lib/clipboard'
import type { HighlightToggles } from './highlightCategories'
import { anchorFrom } from './floating/useReaderOverlays'
import type { SelectionAnchor as Anchor } from './floating/SelectionMenu'
import { ImagePdfRenderer } from './pdf/ImagePdfRenderer'
import type { PdfSource } from './pdf/types'
import {
  CiteHotspots,
  ExplainZones,
  HighlightMemo,
  HighlightOverlays,
  SectionMarkers,
  SectionSparkles,
  SelectionHotspot,
} from './overlays'
import s from './PdfView.module.css'

/** 1쪽 제목 옆 설명 버튼 자리 (목업 좌표) */
const TITLE_SPOT = { x: 406, y: 157.4 }

export interface JumpTarget {
  sectionId?: string
  page?: number
  /** pt 단위 쪽 안 세로 위치 */
  y?: number
}

interface Props {
  reader: PaperReaderPayload
  toggles: HighlightToggles
  /** 아웃라인·노트에서 이동을 요청할 때마다 바뀌는 값 */
  jump: { target: JumpTarget; nonce: number } | null
  onActiveSection: (id: string) => void
  onProgress: (pct: number) => void
  /** 메모 카드의 "채팅에 묻기" — 그 위치를 맥락으로 넘겨요 */
  onAskChat: (sectionId: string, page: number) => void
  /** 메모 카드의 "HTML에서 보기" */
  onOpenHtml: (sectionId: string) => void
  /** 설명 버튼·그림/수식 — 누른 자리를 함께 넘겨요 */
  onExplain: (key: string, anchor: Anchor) => void
  /** 인용 번호 핫스팟 */
  onCite: (n: number, anchor: Anchor) => void
  /** 본문 선택 (지금은 2쪽 핫스팟으로 흉내) */
  onSelect: (anchor: Anchor, text: string, sectionId: string) => void
  /** 선택 흉내 핫스팟에 얹을 표식 — 선택 중 / 내 하이라이트 / 주석 저장됨 */
  selectionMarks?: { active: boolean; highlighted: boolean; annotated: boolean }
  /** 마우스가 올라간 설명 대상 — E 키로 열 때 써요 */
  onHover: (key: string | null, anchor: Anchor | null) => void
  /** 본문 위에 뜨는 것들 */
  floating: ReactNode
  onToast: (msg: string) => void
  /** 끝까지 읽었을 때 */
  nudge: { show: boolean; onMarkDone: () => void; onDismiss: () => void }
}

export function PdfView({
  reader,
  toggles,
  jump,
  onActiveSection,
  onProgress,
  onAskChat,
  onOpenHtml,
  onExplain,
  onCite,
  onSelect,
  selectionMarks,
  onHover,
  floating,
  onToast,
  nudge,
}: Props) {
  const [zoom, setZoom] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const scrollRef = useRef<HTMLDivElement>(null)
  /* 이동 직후에는 관찰자가 다음 섹션으로 덮어쓰지 않게 잠깐 쉬어요 */
  const suppressUntil = useRef(0)
  const pageEls = useRef(new Map<number, HTMLElement>())
  const sectionEls = useRef(new Map<string, HTMLElement>())
  const pageRatios = useRef(new Map<number, number>())
  const sectionTops = useRef<Array<{ id: string; top: number }>>([])

  const source: PdfSource = useMemo(
    () => ({
      pageCount: reader.pageCount,
      pageSize: () => reader.pageSize,
      pageImageUrl: (p) =>
        `${reader.pageImageBase}/p${String(p).padStart(2, '0')}.jpg`,
    }),
    [reader],
  )

  /* ── 현재 쪽: 화면에 가장 많이 보이는 쪽 ─────────────────── */
  useEffect(() => {
    const root = scrollRef.current
    if (!root) return
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const n = Number((e.target as HTMLElement).id.replace('pdf-page-', ''))
          pageRatios.current.set(n, e.intersectionRatio)
        }
        let best = 1
        let bestRatio = -1
        for (const [n, r] of pageRatios.current) {
          if (r > bestRatio) {
            bestRatio = r
            best = n
          }
        }
        setPage(best)
      },
      { root, threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    )
    pageEls.current.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [reader.pageCount])

  /* ── 현재 섹션: 화면 위쪽을 지난 마지막 섹션 ─────────────── */
  useEffect(() => {
    const root = scrollRef.current
    if (!root) return
    const io = new IntersectionObserver(
      () => {
        if (Date.now() < suppressUntil.current) return
        const rootTop = root.getBoundingClientRect().top
        const passed = sectionTops.current
          .map(({ id }) => {
            const el = sectionEls.current.get(id)
            if (!el) return null
            return { id, top: el.getBoundingClientRect().top - rootTop }
          })
          .filter((x): x is { id: string; top: number } => x !== null)
          .filter((x) => x.top <= 90)
        const last = passed[passed.length - 1]
        if (last) onActiveSection(last.id)
      },
      // 위쪽 90px 띠를 지나는 순간을 잡아요
      { root, rootMargin: '-90px 0px 0px 0px', threshold: 0 },
    )
    sectionEls.current.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [onActiveSection, reader.sections])

  /* ── 읽은 위치 % ─────────────────────────────────────────── */
  const reportProgress = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const max = el.scrollHeight - el.clientHeight
    // 쪽 이미지가 붙기 전에는 스크롤 길이가 0이에요.
    // 그때 100%로 보고하면 완료 안내가 바로 떠 버려요.
    if (max <= 4) return
    // 소수점 높이 때문에 끝에서 99% 로 멈추는 걸 막아요
    const pct = el.scrollTop >= max - 2 ? 100 : Math.round((el.scrollTop / max) * 100)
    onProgress(pct)
  }, [onProgress])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        reportProgress()
      })
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    // 쪽 이미지가 하나씩 붙으면 전체 높이가 바뀌니 그때마다 다시 재요
    const ro = new ResizeObserver(onScroll)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    reportProgress()
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
      if (frame) cancelAnimationFrame(frame)
    }
  }, [reportProgress])

  /* ── 이동 ────────────────────────────────────────────────── */
  const scrollTo = useCallback(
    (target: JumpTarget, smooth = true) => {
      const root = scrollRef.current
      if (!root) return
      const sec = target.sectionId
        ? reader.sections.find((x) => x.id === target.sectionId)
        : undefined
      const pageNo = target.page ?? sec?.page ?? 1
      const pageEl = pageEls.current.get(pageNo)
      if (!pageEl) return
      const y = target.y ?? sec?.y ?? 0
      const offset = (y / reader.pageSize.height) * pageEl.offsetHeight
      suppressUntil.current = Date.now() + (smooth ? 700 : 300)
      root.scrollTo({
        top: pageEl.offsetTop + offset - 60,
        behavior: smooth ? 'smooth' : 'auto',
      })
    },
    [reader.sections, reader.pageSize.height],
  )

  useEffect(() => {
    if (jump) scrollTo(jump.target)
    // nonce 가 바뀔 때마다 한 번씩 이동해요
  }, [jump?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  /* ── 확대·축소: 보던 쪽을 유지해요 ───────────────────────── */
  const changeZoom = (next: number) => {
    const keep = page
    setZoom(next)
    // 쪽 크기가 바뀐 다음에 다시 맞춰요
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollTo({ page: keep }, false))
    })
  }

  const zoomIndex = reader.zoomLevels.indexOf(zoom)
  const zoomOut = () => {
    const i = Math.max(0, zoomIndex - 1)
    if (reader.zoomLevels[i] !== undefined) changeZoom(reader.zoomLevels[i])
  }
  const zoomIn = () => {
    const i = Math.min(reader.zoomLevels.length - 1, zoomIndex + 1)
    if (reader.zoomLevels[i] !== undefined) changeZoom(reader.zoomLevels[i])
  }
  const fitWidth = () => {
    const root = scrollRef.current
    if (!root) return
    // 좌우 여백 20px 씩을 빼고 가장 가까운 단계를 골라요
    const want = (root.clientWidth - 40) / reader.baseWidth
    const best = reader.zoomLevels.reduce((a, b) =>
      Math.abs(b - want) < Math.abs(a - want) ? b : a,
    )
    changeZoom(best)
  }

  const goPage = (n: number) => {
    const clamped = Math.max(1, Math.min(reader.pageCount, n))
    scrollTo({ page: clamped })
  }

  /* ── 복사 ────────────────────────────────────────────────── */
  const copyZone = async (z: ExplainZone) => {
    if (z.latex) {
      await copyText(z.latex)
      onToast('LaTeX를 복사했어요')
    } else {
      onToast('그림 복사는 다음 단계에서 붙여요')
    }
  }

  const anchorAt = (el: HTMLElement | null): Anchor | null => {
    const root = scrollRef.current
    return el && root ? anchorFrom(el, root) : null
  }
  const openAt = (key: string, el: HTMLElement | null) => {
    const a = anchorAt(el)
    if (a) onExplain(key, a)
  }

  const visible = (h: Highlight) => toggles[h.category]
  const selected = reader.highlights.find((h) => h.id === selectedId) ?? null

  return (
    <div className={s.view}>
      <div className={s.scroll} ref={scrollRef}>
        <div className={s.toolbar}>
          <IconButton label="이전 쪽" onClick={() => goPage(page - 1)}>
            <ChevronUp />
          </IconButton>
          <span className={s.pageLabel}>
            쪽 <span className={s.pageNow}>{page}</span>{' '}
            <span className={s.pageTotal}>/ {reader.pageCount}</span>
          </span>
          <IconButton label="다음 쪽" onClick={() => goPage(page + 1)}>
            <ChevronDown />
          </IconButton>
          <span aria-hidden="true" className={s.divider} />
          <IconButton label="축소" onClick={zoomOut} disabled={zoomIndex <= 0}>
            <span aria-hidden="true">−</span>
          </IconButton>
          <span className={s.zoomLabel}>{Math.round(zoom * 100)}%</span>
          <IconButton
            label="확대"
            onClick={zoomIn}
            disabled={zoomIndex >= reader.zoomLevels.length - 1}
          >
            <span aria-hidden="true">+</span>
          </IconButton>
          <button type="button" onClick={fitWidth} className={s.fit}>
            폭 맞춤
          </button>
          <span className={s.hint}>
            attention.pdf · 하이라이트를 누르면 메모가 보여요
          </span>
        </div>

        <ImagePdfRenderer
          source={source}
          baseWidth={reader.baseWidth}
          zoom={zoom}
          onPageElement={(p, el) => {
            if (el) pageEls.current.set(p, el)
            else pageEls.current.delete(p)
          }}
        >
          {(ctx) => {
            const pageHighlights = reader.highlights.filter(
              (h) => h.page === ctx.page && visible(h),
            )
            const pageSections = reader.sections.filter((x) => x.page === ctx.page)
            return (
              <>
                <SectionMarkers
                  sections={pageSections}
                  pageHeight={reader.pageSize.height}
                  onMarker={(id, el) => {
                    if (el) {
                      sectionEls.current.set(id, el)
                      sectionTops.current = reader.sections.map((x) => ({ id: x.id, top: 0 }))
                    } else sectionEls.current.delete(id)
                  }}
                />
                <HighlightOverlays
                  ctx={ctx}
                  highlights={pageHighlights}
                  selectedId={selectedId}
                  onSelect={(h) => {
                    setSelectedId((prev) => (prev === h.id ? null : h.id))
                    onActiveSection(h.section)
                  }}
                />
                <ExplainZones
                  ctx={ctx}
                  zones={reader.explainZones.filter((z) => z.page === ctx.page)}
                  onExplain={(key, el) => openAt(key, el)}
                  onCopy={copyZone}
                  onHover={(key, el) =>
                    onHover(key, key && el ? anchorAt(el) : null)
                  }
                />
                <CiteHotspots
                  ctx={ctx}
                  spots={reader.citeSpots.filter((c) => c.page === ctx.page)}
                  onPick={(n, el) => {
                    const a = anchorAt(el)
                    if (a) onCite(n, a)
                  }}
                />
                <SelectionHotspot
                  ctx={ctx}
                  spot={reader.selectionSpot}
                  active={selectionMarks?.active}
                  highlighted={selectionMarks?.highlighted}
                  annotated={selectionMarks?.annotated}
                  onPick={(el: HTMLElement) => {
                    const a = anchorAt(el)
                    if (a) onSelect(a, reader.selectionSpot.text, 's1')
                  }}
                />
                <SectionSparkles
                  ctx={ctx}
                  sections={pageSections}
                  titleSpot={ctx.page === 1 ? TITLE_SPOT : null}
                  onExplain={(key, el) => openAt(key, el)}
                  onHover={(key, el) =>
                    onHover(key, key && el ? anchorAt(el) : null)
                  }
                />
                {selected && selected.page === ctx.page && (
                  <HighlightMemo
                    ctx={ctx}
                    highlight={selected}
                    pageWidth={reader.pageSize.width}
                    pageHeight={reader.pageSize.height}
                    onAsk={() => onAskChat(selected.section, selected.page)}
                    onOpenHtml={() => onOpenHtml(selected.section)}
                    onClose={() => setSelectedId(null)}
                  />
                )}
              </>
            )
          }}
        </ImagePdfRenderer>

        {floating}
      </div>

      {nudge.show && (
        <div role="status" className={s.nudge}>
          <span className={s.nudgeText}>끝까지 읽었어요. 완료로 표시할까요?</span>
          <Button variant="primary" size="sm" onClick={nudge.onMarkDone}>
            완료로 표시
          </Button>
          <Button size="sm" onClick={nudge.onDismiss}>
            나중에
          </Button>
        </div>
      )}
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

const ChevronUp = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M6 15l6-6 6 6" />
  </svg>
)
const ChevronDown = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M6 9l6 6 6-6" />
  </svg>
)
