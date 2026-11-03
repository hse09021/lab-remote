import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import type { PtRect } from '@/api/types'
import { loadPdf } from './pdfjs'
// pdfjs 의 글자 층 모양 (span 배치·선택 색)
import 'pdfjs-dist/web/pdf_viewer.css'
import type { PdfPageContext, PdfRendererProps } from './types'
import s from './PdfJsRenderer.module.css'

/** 보이는 쪽에서 이만큼 떨어진 쪽까지만 그려요 */
const NEAR = 1

interface Props extends PdfRendererProps {
  url: string
  /** PDF 를 못 읽었을 때 대신 보여 줄 것 */
  fallback: React.ReactNode
  /** 실제 텍스트 선택 */
  onSelect?: (rects: PtRect[], text: string, page: number) => void
}

export function PdfJsRenderer({
  source,
  baseWidth,
  zoom,
  children,
  onPageElement,
  url,
  fallback,
  onSelect,
}: Props) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [failed, setFailed] = useState(false)
  /** 지금 그려 둘 쪽 번호 */
  const [near, setNear] = useState<number[]>([1])
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let alive = true
    void loadPdf(url).then((d) => {
      if (!alive) return
      if (d) setDoc(d)
      else setFailed(true)
    })
    return () => {
      alive = false
    }
  }, [url])

  /* 보이는 쪽 둘레만 그려요 — 15쪽을 한꺼번에 그리지 않아요 */
  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const io = new IntersectionObserver(
      (entries) => {
        setNear((prev) => {
          const shown = new Set(prev)
          for (const e of entries) {
            const n = Number((e.target as HTMLElement).dataset.page)
            if (!n) continue
            if (e.isIntersecting) {
              for (let p = n - NEAR; p <= n + NEAR; p++) {
                if (p >= 1 && p <= source.pageCount) shown.add(p)
              }
            }
          }
          // 멀어진 쪽은 버려요
          const visible = entries.filter((e) => e.isIntersecting).map((e) => Number((e.target as HTMLElement).dataset.page))
          if (visible.length) {
            const lo = Math.min(...visible) - NEAR
            const hi = Math.max(...visible) + NEAR
            for (const p of [...shown]) if (p < lo || p > hi) shown.delete(p)
          }
          const next = [...shown].sort((a, b) => a - b)
          return next.join() === prev.join() ? prev : next
        })
      },
      { root: root.closest('[data-pdf-scroll]') ?? null, rootMargin: '200px 0px' },
    )

    root.querySelectorAll('[data-page]').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [source.pageCount, doc])

  const pages = useMemo(
    () => Array.from({ length: source.pageCount }, (_, i) => i + 1),
    [source.pageCount],
  )

  if (failed) return <>{fallback}</>

  return (
    <div ref={rootRef} className={s.doc}>
      {pages.map((page) => (
        <PdfPage
          key={page}
          doc={doc}
          page={page}
          size={source.pageSize(page)}
          width={baseWidth * zoom}
          render={near.includes(page)}
          onElement={onPageElement}
          onSelect={onSelect}
        >
          {children}
        </PdfPage>
      ))}
    </div>
  )
}

/* ── 쪽 하나 ──────────────────────────────────────────────── */

function PdfPage({
  doc,
  page,
  size,
  width,
  render,
  onElement,
  onSelect,
  children,
}: {
  doc: PDFDocumentProxy | null
  page: number
  size: { width: number; height: number }
  width: number
  render: boolean
  onElement?: (page: number, el: HTMLElement | null) => void
  onSelect?: (rects: PtRect[], text: string, page: number) => void
  children: (ctx: PdfPageContext) => React.ReactNode
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textRef = useRef<HTMLDivElement>(null)
  const [drawn, setDrawn] = useState(false)

  const height = (width / size.width) * size.height

  useEffect(() => {
    onElement?.(page, hostRef.current)
    return () => onElement?.(page, null)
  }, [onElement, page])

  /* 그리기 — 화면 배율을 반영해 선명하게 */
  useEffect(() => {
    if (!doc || !render) return
    let cancelled = false
    let task: { cancel: () => void } | null = null

    void (async () => {
      const pdfPage = await doc.getPage(page)
      if (cancelled) return

      const canvas = canvasRef.current
      const layer = textRef.current
      if (!canvas || !layer) return

      const viewport = pdfPage.getViewport({ scale: width / size.width })
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * dpr)
      canvas.height = Math.floor(viewport.height * dpr)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`

      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const r = pdfPage.render({ canvas, canvasContext: ctx, viewport })
      task = r
      await r.promise.catch(() => {})
      if (cancelled) return

      // 투명 글자 층 — 드래그 선택이 여기서 일어나요
      layer.replaceChildren()
      layer.style.setProperty('--scale-factor', String(viewport.scale))
      const pdfjs = await import('pdfjs-dist')
      const textLayer = new pdfjs.TextLayer({
        textContentSource: await pdfPage.getTextContent(),
        container: layer,
        viewport,
      })
      await textLayer.render().catch(() => {})
      if (!cancelled) setDrawn(true)
    })()

    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [doc, page, render, width, size.width])

  /* 그리지 않는 쪽은 비워 메모리를 돌려줘요 */
  useEffect(() => {
    if (render) return
    const canvas = canvasRef.current
    if (canvas) {
      canvas.width = 0
      canvas.height = 0
    }
    textRef.current?.replaceChildren()
    setDrawn(false)
  }, [render])

  /** 화면 px → pt(왼쪽 위 기준) */
  const toPt = useCallback(
    (px: number) => (px / width) * size.width,
    [width, size.width],
  )

  const ctx: PdfPageContext = useMemo(
    () => ({
      page,
      rectToStyle: (box: PtRect) => ({
        position: 'absolute',
        left: `${(box[0] / size.width) * 100}%`,
        top: `${(box[1] / size.height) * 100}%`,
        width: `${((box[2] - box[0]) / size.width) * 100}%`,
        height: `${((box[3] - box[1]) / size.height) * 100}%`,
      }),
      pointToStyle: (x: number, y: number) => ({
        position: 'absolute',
        left: `${(x / size.width) * 100}%`,
        top: `${(y / size.height) * 100}%`,
      }),
      getSelectionRects: () => {
        const host = hostRef.current
        const sel = window.getSelection()
        if (!host || !sel || sel.isCollapsed || sel.rangeCount === 0) return null
        const range = sel.getRangeAt(0)
        if (!host.contains(range.commonAncestorContainer)) return null

        const base = host.getBoundingClientRect()
        const rects: PtRect[] = []
        for (const r of Array.from(range.getClientRects())) {
          if (r.width < 1 || r.height < 1) continue
          rects.push([
            toPt(r.left - base.left),
            toPt(r.top - base.top),
            toPt(r.right - base.left),
            toPt(r.bottom - base.top),
          ])
        }
        return rects.length ? rects : null
      },
    }),
    [page, size.width, size.height, toPt],
  )

  return (
    <div
      ref={hostRef}
      id={`pdf-page-${page}`}
      data-page={page}
      aria-label={`${page}쪽`}
      style={{ width, height }}
      className={s.page}
      onMouseUp={() => {
        if (!onSelect) return
        const rects = ctx.getSelectionRects()
        const text = window.getSelection()?.toString().trim() ?? ''
        if (rects && text.length >= 2) onSelect(rects, text, page)
      }}
    >
      <canvas ref={canvasRef} className={s.canvas} />
      {/*
        글자 층 — 보이지 않지만 선택이 돼요.
        pdfjs 의 pdf_viewer.css 는 전역 .textLayer 를 노리니 그 이름을 꼭 같이 줘요
        (CSS Module 해시 이름만 주면 span 위치 규칙이 안 먹어요).
      */}
      <div ref={textRef} className={`textLayer ${s.textLayerBox}`} />
      {!drawn && <div aria-hidden="true" className={s.placeholder} />}
      {/* 오버레이는 글자 층 위에 올라가요 */}
      <div className={s.overlay}>{children(ctx)}</div>
    </div>
  )
}
