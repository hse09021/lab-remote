import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analysisQuery, paperPdfHref } from '@/api/papers'
import type { PaperAnalysis } from '@/api/papers'
import type { Highlight, Paper, PaperReaderPayload, PaperSection, PtRect, Reference } from '@/api/types'
import { loadPdf } from './pdf/pdfjs'
import type { PDFDocumentProxy } from './pdf/pdfjs'

/**
 * vault에서 온 논문의 리더 데이터를 **PDF에서** 만들어요.
 *
 * mock 논문(attn)은 섹션 · 하이라이트 · 설명 자리까지 미리 만든 데이터가 있지만,
 * vault 논문은 PDF 하나뿐이에요. 그래서 쪽 수 · 쪽 크기 · 목차(PDF 책갈피)를 읽어
 * 같은 리더 화면에 넣어요. AI 설명 · 하이라이트 · 참고문헌은 아직 없어요.
 */
export function useVaultReader(id: string, paper: Paper | undefined, enabled: boolean) {
  const [base, setBase] = useState<PaperReaderPayload | null>(null)
  const [data, setData] = useState<PaperReaderPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const url = paperPdfHref(id)
  const want = enabled && !!paper?.hasPdf
  // AI 분석(하이라이트 구절 · 참고문헌) — 있으면 PDF 글자 층에서 자리를 찾아 얹어요
  const an = useQuery(analysisQuery(id, want))
  const analysis = an.data?.analysis ?? null

  useEffect(() => {
    if (!base) return
    if (!analysis) {
      setData(base)
      return
    }
    let alive = true
    void loadPdf(url).then(async (doc) => {
      if (!doc || !alive) return
      const extra = await fromAnalysis(doc, base, analysis)
      if (alive) setData({ ...base, ...extra })
    })
    return () => {
      alive = false
    }
  }, [base, analysis, url])

  useEffect(() => {
    if (!want || !paper) return
    let alive = true
    setBase(null)
    setData(null)
    setFailed(false)
    void loadPdf(url).then(async (doc) => {
      if (!alive) return
      if (!doc) {
        setFailed(true)
        return
      }
      const built = await build(doc, url, paper)
      if (alive) setBase(built)
    })
    return () => {
      alive = false
    }
  }, [want, url, paper])

  return { data, failed, active: want, analysis, analyzing: !!an.data?.running }
}

async function build(doc: PDFDocumentProxy, url: string, paper: Paper): Promise<PaperReaderPayload> {
  const first = await doc.getPage(1)
  const vp = first.getViewport({ scale: 1 })
  const pageSize = { width: Math.round(vp.width), height: Math.round(vp.height) }
  const arxiv = arxivOf(paper)
  return {
    paperId: paper.id,
    title: paper.title,
    meta: [paper.authors, paper.venue].filter(Boolean).join(' · '),
    arxivId: arxiv,
    arxivUrl: arxiv ? `https://arxiv.org/abs/${arxiv}` : '',
    hasHtml: false,
    pageCount: doc.numPages,
    pageImageBase: '',
    pageSize,
    sections: await outline(doc, pageSize.height),
    highlights: [],
    references: [],
    referenceTotal: 0,
    citationsCaption: '',
    pdfUrl: url,
    baseWidth: 700,
    zoomLevels: [0.75, 1, 1.25, 1.5],
    explainZones: [],
    citeSpots: [],
    extractedConfig: { title: '', caption: '', rows: [] },
    discrepancy: { title: '', text: '', options: [], chosen: null },
    inlineMemo: { title: '', meta: '', text: '' },
    topics: {},
    terms: {},
    selectionSpot: { page: 0, box: [0, 0, 0, 0], text: '', translation: '', translationNote: '' },
  }
}

/** 노트 앞쪽 메타의 arXiv 번호 (없으면 "") */
const arxivOf = (paper: Paper) => paper.arxiv ?? ''

interface OutlineItem {
  title: string
  dest: string | unknown[] | null
  items: OutlineItem[]
}

/** PDF 책갈피 → 섹션 (대제목 · 하위 두 단계까지) */
async function outline(doc: PDFDocumentProxy, pageHeight: number): Promise<PaperSection[]> {
  let items: OutlineItem[] | null = null
  try {
    items = (await doc.getOutline()) as OutlineItem[] | null
  } catch {
    items = null
  }
  if (!items?.length) return []
  const out: PaperSection[] = []
  const walk = async (list: OutlineItem[], level: 0 | 1 | 2) => {
    for (const item of list) {
      const place = await resolve(doc, item.dest)
      if (place) {
        const m = item.title.trim().match(/^((?:\d+|[A-Z])(?:\.\d+)*)\.?\s+(.*)$/)
        out.push({
          id: `o${out.length + 1}`,
          n: m ? m[1] : '',
          title: m ? m[2] : item.title.trim(),
          level,
          page: place.page,
          y: Math.max(0, Math.round(pageHeight - place.y)),
          xEnd: 0,
          htmlAnchor: null,
        })
      }
      if (item.items?.length && level < 2) await walk(item.items, (level + 1) as 1 | 2)
    }
  }
  await walk(items, 0)
  return out
}

async function resolve(doc: PDFDocumentProxy, dest: OutlineItem['dest']): Promise<{ page: number; y: number } | null> {
  try {
    const explicit = typeof dest === 'string' ? await doc.getDestination(dest) : dest
    if (!Array.isArray(explicit) || !explicit[0]) return null
    const page = (await doc.getPageIndex(explicit[0] as Parameters<PDFDocumentProxy['getPageIndex']>[0])) + 1
    const y = typeof explicit[3] === 'number' ? explicit[3] : 0
    return { page, y }
  } catch {
    return null
  }
}

/* ── AI 분석 → 리더 데이터 ─────────────────────────────────────── */

async function fromAnalysis(
  doc: PDFDocumentProxy,
  base: PaperReaderPayload,
  analysis: PaperAnalysis,
): Promise<Pick<PaperReaderPayload, 'highlights' | 'references' | 'referenceTotal' | 'citationsCaption'>> {
  const highlights: Highlight[] = []
  for (const [i, h] of analysis.highlights.entries()) {
    const found = await locateNear(doc, h.page, h.quote, base.pageSize.height, base.pageCount)
    if (!found) continue
    const section = [...base.sections].reverse().find((x) => x.page <= found.page)?.id ?? ''
    highlights.push({ id: `ai-${i}`, category: h.category, section, page: found.page, boxes: found.boxes, note: h.note, htmlBlock: null })
  }
  const references: Reference[] = analysis.references.map((r) => {
    const first = (r.authors.split(/,| and /)[0] ?? '').trim().split(/\s+/).pop() ?? ''
    return {
      n: r.n,
      authors: r.authors,
      short: `${first}${r.authors.includes(',') || r.authors.includes(' and ') ? ' et al.' : ''}, ${r.year || ''}`.trim(),
      title: r.title,
      venue: r.venue,
      arxiv: r.arxiv || null,
      year: r.year,
      citedCount: 0,
      inLibrary: false,
      why: r.why,
    }
  })
  return {
    highlights,
    references,
    referenceTotal: references.length,
    citationsCaption: `AI 분석으로 뽑은 참고문헌 ${references.length}개`,
  }
}

/** 쪽 번호가 한 쪽 어긋나도 찾아요 */
async function locateNear(doc: PDFDocumentProxy, page: number, quote: string, pageHeight: number, pageCount: number) {
  for (const p of [page, page + 1, page - 1]) {
    if (p < 1 || p > pageCount) continue
    const boxes = await locate(doc, p, quote, pageHeight)
    if (boxes.length) return { page: p, boxes }
  }
  return null
}

const norm = (t: string) => t.toLowerCase().replace(/[\u2010-\u2015-]/g, '-').replace(/\s+/g, ' ')

/** 쪽 글자 층에서 구절을 찾아 그 글자 조각들의 사각형(pt, 위에서부터)을 돌려줘요 */
async function locate(doc: PDFDocumentProxy, page: number, quote: string, pageHeight: number): Promise<PtRect[]> {
  try {
    const pg = await doc.getPage(page)
    const tc = await pg.getTextContent()
    const items = tc.items.filter((it): it is typeof it & { str: string; transform: number[]; width: number; height: number } => 'str' in it)
    // 글자 조각을 이어 붙이고 각 글자가 어느 조각에서 왔는지 기억해요 (공백은 하나로)
    let text = ''
    const owner: number[] = []
    items.forEach((it, idx) => {
      for (const ch of `${it.str} `) {
        const c = /\s/.test(ch) ? ' ' : /[\u2010-\u2015]/.test(ch) ? '-' : ch
        if (c === ' ' && text.endsWith(' ')) continue
        text += c.toLowerCase()
        owner.push(idx)
      }
    })
    const q = norm(quote).trim()
    let at = text.indexOf(q)
    let len = q.length
    if (at < 0 && q.length > 60) {
      at = text.indexOf(q.slice(0, 60))
      len = 60
    }
    if (at < 0) return []
    const used = [...new Set(owner.slice(at, at + len))]
    return used.map((idx) => {
      const it = items[idx]
      const [, , , d, e, f] = it.transform
      const h = it.height || Math.abs(d) || 10
      return [e, pageHeight - f - h, e + it.width, pageHeight - f + h * 0.2] as PtRect
    })
  } catch {
    return []
  }
}
