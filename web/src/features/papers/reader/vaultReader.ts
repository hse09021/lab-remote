import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analysisQuery, paperPdfHref } from '@/api/papers'
import type { PaperAnalysis } from '@/api/papers'
import type { ExplainSpot, Highlight, Paper, PaperReaderPayload, PaperSection, PtRect, Reference } from '@/api/types'
import { loadPdf } from './pdf/pdfjs'
import type { PDFDocumentProxy } from './pdf/pdfjs'

/**
 * vault에서 온 논문의 리더 데이터를 **PDF에서** 만들어요.
 *
 * mock 논문(attn)은 섹션 · 하이라이트 · 설명 자리까지 미리 만든 데이터가 있지만,
 * vault 논문은 PDF 하나뿐이에요. 그래서 쪽 수 · 쪽 크기 · 목차(PDF 책갈피)를 읽어
 * 같은 리더 화면에 넣어요. AI 설명은 누를 때 서버에 묻고, 하이라이트 · 참고문헌은 'AI 분석'으로 채워요.
 */
export function useVaultReader(id: string, paper: Paper | undefined, enabled: boolean) {
  const [base, setBase] = useState<PaperReaderPayload | null>(null)
  const [data, setData] = useState<PaperReaderPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const url = paperPdfHref(id)
  const want = enabled && !!paper?.hasPdf
  // 목록을 새로 받을 때마다(읽음 상태 · HTML 받기) PDF를 다시 열지 않게, 리더에 쓰는 값만 봐요
  const paperRef = useRef(paper)
  paperRef.current = paper
  const paperKey = paper ? JSON.stringify([paper.id, paper.title, paper.authors, paper.venue, paper.arxiv ?? '']) : ''
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
    const paper = paperRef.current
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
  }, [want, url, paperKey])

  // HTML 받기 상태는 바뀌어도 PDF를 다시 열 필요가 없어요
  const hasHtml = !!paper?.arxiv && paper.htmlState !== 'none'
  const out = useMemo(() => (data ? { ...data, hasHtml } : null), [data, hasHtml])
  return { data: out, failed, active: want, analysis, analyzing: !!an.data?.running }
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
    // arXiv 논문은 HTML도 볼 수 있어요 — 안 받았으면 누를 때 받아요 (arXiv에 없으면 PDF만). 위에서 덮어써요
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
    explainSpots: await elementSpots(doc, pageSize),
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

/* ── 그림 · 표 · 수식 찾기 ─────────────────────────────────────── */

type TextItem = { str: string; transform: number[]; width: number; height: number }
interface Line {
  y: number
  h: number
  x0: number
  x1: number
  items: TextItem[]
  text: string
}

/** 한 쪽의 글자 조각을 줄로 묶어요 (같은 높이 · 왼쪽부터). 두 단 논문도 단마다 따로 묶여요 */
function linesOf(items: TextItem[], pageWidth: number): Line[] {
  const rows = new Map<number, TextItem[]>()
  for (const it of items) {
    if (!it.str.trim()) continue
    const y = Math.round(it.transform[5]! / 2) * 2
    rows.set(y, [...(rows.get(y) ?? []), it])
  }
  const out: Line[] = []
  for (const [y, row] of rows) {
    row.sort((a, b) => a.transform[4]! - b.transform[4]!)
    // 가로로 크게 떨어진 조각(두 단의 왼쪽 · 오른쪽)은 다른 줄이에요
    let cur: TextItem[] = []
    const flush = () => {
      if (!cur.length) return
      const x0 = cur[0]!.transform[4]!
      const last = cur[cur.length - 1]!
      out.push({ y, h: Math.max(...cur.map((c) => c.height || Math.abs(c.transform[3]!) || 8)), x0, x1: last.transform[4]! + last.width, items: cur, text: cur.map((c) => c.str).join(' ').replace(/\s+/g, ' ').trim() })
      cur = []
    }
    for (const it of row) {
      const prev = cur[cur.length - 1]
      if (prev && it.transform[4]! - (prev.transform[4]! + prev.width) > pageWidth * 0.08) flush()
      cur.push(it)
    }
    flush()
  }
  return out.sort((a, b) => b.y - a.y || a.x0 - b.x0)
}

const CAPTION = /^(Figure|Fig\.|FIGURE|Table|TABLE)\s*([A-Z]?\d+(?:\.\d+)?)\s*[:.|]/
const EQNO = /^\((\d+[a-z]?)\)$/

/**
 * PDF 글자 층에서 그림 · 표 캡션("Figure 3:" · "Table 2.")과 식 번호("(4)")를 찾아
 * 그 옆에 둘 설명 버튼 자리를 만들어요. 그림 · 그래프는 캡션 옆, 수식은 번호 옆이에요.
 */
async function elementSpots(doc: PDFDocumentProxy, size: { width: number; height: number }): Promise<ExplainSpot[]> {
  const spots: ExplainSpot[] = []
  const seen = new Set<string>()
  for (let p = 1; p <= doc.numPages && spots.length < 150; p++) {
    let items: TextItem[]
    try {
      const tc = await (await doc.getPage(p)).getTextContent()
      items = tc.items.filter((it): it is typeof it & TextItem => 'str' in it)
    } catch {
      continue
    }
    const lines = linesOf(items, size.width)
    lines.forEach((ln, i) => {
      const cap = ln.text.match(CAPTION)
      if (cap) {
        const table = /^t/i.test(cap[1]!)
        const label = `${table ? 'Table' : 'Figure'} ${cap[2]}`
        if (seen.has(label)) return
        seen.add(label)
        // 캡션은 아래 줄까지 이어져요 — 같은 단에서 줄 간격이 벌어지기 전까지
        let text = ln.text
        let prevY = ln.y
        for (const next of lines.slice(i + 1)) {
          if (Math.abs(next.x0 - ln.x0) > size.width * 0.25) continue
          if (prevY - next.y > ln.h * 2.2 || text.length > 500) break
          text += ' ' + next.text
          prevY = next.y
        }
        const x = ln.x0 - 34 >= 4 ? ln.x0 - 34 : ln.x1 + 6
        spots.push({ key: `el:${p}:${label}`, kind: table ? 'table' : 'fig', page: p, x, y: size.height - ln.y - ln.h / 2, label, text: text.slice(0, 600) })
        return
      }
      const last = ln.items[ln.items.length - 1]!
      const eq = last.str.trim().match(EQNO)
      if (eq) {
        let body: string
        if (ln.items.length > 1) {
          const prev = ln.items[ln.items.length - 2]!
          // 식 번호는 오른쪽 끝에 떨어져 있어요 (본문 속 "(1)"과 구분)
          if (last.transform[4]! - (prev.transform[4]! + prev.width) < 18) return
          body = ln.items.slice(0, -1).map((c) => c.str).join(' ')
        } else {
          // 번호만 따로 떨어진 줄 — 같은 높이 왼쪽의 식을 붙여요. 왼쪽 여백에 있으면 식 번호가 아니에요
          if (ln.x0 < size.width * 0.3) return
          body = lines.filter((o) => o !== ln && Math.abs(o.y - ln.y) <= ln.h && o.x1 < ln.x0).map((o) => o.text).join(' ')
        }
        const label = `식 (${eq[1]})`
        if (seen.has(label)) return
        seen.add(label)
        body = body.replace(/\s+/g, ' ').trim()
        const x = Math.min(last.transform[4]! + last.width + 6, size.width - 32)
        spots.push({ key: `el:${p}:${label}`, kind: 'eq', page: p, x, y: size.height - ln.y - ln.h / 2, label, text: body.slice(0, 400) })
      }
    })
  }
  return spots
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
    // 하이라이트 첫 줄보다 위에서 시작한 마지막 섹션 (같은 쪽이면 세로 위치까지 봐요)
    const top = found.boxes[0]?.[1] ?? 0
    const section =
      [...base.sections].reverse().find((x) => x.page < found.page || (x.page === found.page && x.y <= top + 4))?.id ?? ''
    highlights.push({ id: `ai-${i}`, category: h.category, section, page: found.page, boxes: found.boxes, note: h.note, htmlBlock: null, quote: h.quote })
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
    // 그 글자가 조각 안 몇 번째 글자인지 (뒤에 붙인 공백은 조각 끝)
    const offset: number[] = []
    items.forEach((it, idx) => {
      ;[...`${it.str} `].forEach((ch, pos) => {
        const c = /\s/.test(ch) ? ' ' : /[\u2010-\u2015]/.test(ch) ? '-' : ch
        if (c === ' ' && text.endsWith(' ')) return
        text += c.toLowerCase()
        owner.push(idx)
        offset.push(Math.min(pos, it.str.length))
      })
    })
    const q = norm(quote).trim()
    let at = text.indexOf(q)
    let len = q.length
    if (at < 0 && q.length > 60) {
      at = text.indexOf(q.slice(0, 60))
      len = 60
    }
    if (at < 0) return []
    // 조각마다 구절이 걸친 글자만큼만 칠해요 (조각 하나가 한 줄 전체일 때가 많아요).
    // 글자 폭은 알 수 없어서 조각 폭을 글자 수로 나눠 어림해요
    const span = new Map<number, [number, number]>()
    for (let k = at; k < at + len; k++) {
      const idx = owner[k]!
      const pos = offset[k]!
      const cur = span.get(idx)
      span.set(idx, cur ? [Math.min(cur[0], pos), Math.max(cur[1], pos + 1)] : [pos, pos + 1])
    }
    return [...span.entries()].filter(([idx, [a]]) => a < Math.max(1, items[idx]!.str.length)).map(([idx, [a, b]]) => {
      const it = items[idx]
      const [, , , d, e, f] = it.transform
      const h = it.height || Math.abs(d) || 10
      const n = Math.max(1, it.str.length)
      const x0 = e + (it.width * Math.min(a, n)) / n
      const x1 = e + (it.width * Math.min(b, n)) / n
      return [x0, pageHeight - f - h, Math.max(x1, x0 + 2), pageHeight - f + h * 0.2] as PtRect
    })
  } catch {
    return []
  }
}
