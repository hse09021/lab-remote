import { useEffect, useState } from 'react'
import { paperPdfHref } from '@/api/papers'
import type { Paper, PaperReaderPayload, PaperSection } from '@/api/types'
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
  const [data, setData] = useState<PaperReaderPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const url = paperPdfHref(id)
  const want = enabled && !!paper?.hasPdf

  useEffect(() => {
    if (!want || !paper) return
    let alive = true
    setData(null)
    setFailed(false)
    void loadPdf(url).then(async (doc) => {
      if (!alive) return
      if (!doc) {
        setFailed(true)
        return
      }
      const built = await build(doc, url, paper)
      if (alive) setData(built)
    })
    return () => {
      alive = false
    }
  }, [want, url, paper])

  return { data, failed, active: want }
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
