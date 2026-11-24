import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { UserAnnotation } from '@/api/annotations'
import type { PaperReaderPayload } from '@/api/types'
import { Button } from '@/components'
import { copyText } from '@/lib/clipboard'
import type { HighlightToggles } from '../highlightCategories'
import { anchorFrom, anchorFromRect } from '../floating/useReaderOverlays'
import type { SelectionAnchor as Anchor } from '../floating/SelectionMenu'
import { MyHighlightLayer } from '../MyHighlightLayer'
import { placeFromRange } from '../selectionPlace'
import type { SelectionPlace } from '../selectionPlace'
import type { CiteJump } from '../PdfView'
import { loadPaperHtml } from './loadPaperHtml'
import { ConfigCard, MemoCard } from './blocks'
import { Sparkle } from './Sparkle'
import s from './HtmlView.module.css'
import '@/styles/paper.css'

export interface HtmlJump {
  sectionId: string
  /** AI 하이라이트 구절로 (찾으면 섹션보다 먼저) */
  highlightId?: string
  nonce: number
}

interface Props {
  reader: PaperReaderPayload
  toggles: HighlightToggles
  jump: HtmlJump | null
  onActiveSection: (id: string) => void
  onProgress: (pct: number) => void
  /** 설명 버튼·그림·수식 — 누른 자리를 함께 넘겨요 (그림 · 표 · 수식은 캡션 · 식 글자도) */
  onExplain: (key: string, anchor: Anchor, context?: string | null) => void
  /** 본문 인용 칩 */
  onCite: (n: number, anchor: Anchor) => void
  /** 인용 탭에서 고른 참고문헌 — 본문 인용 위치로 가서 인용 카드를 열어요 */
  citeJump?: CiteJump | null
  /** 실제 드래그 선택 — 다시 그릴 자리(블록 id + 오프셋)까지 넘겨요 */
  onSelect: (anchor: Anchor, text: string, sectionId: string, place: SelectionPlace) => void
  /** 내가 칠한 하이라이트 (저장소에 있어요) */
  myHighlights: UserAnnotation[]
  /** 본문의 내 하이라이트를 눌렀을 때 */
  onMyHighlight: (annotation: UserAnnotation, anchor: Anchor) => void
  onHover: (key: string | null, anchor: Anchor | null) => void
  floating: ReactNode
  onToast: (msg: string) => void
  nudge: { show: boolean; onMarkDone: () => void; onDismiss: () => void }
}

export function HtmlView({
  reader,
  toggles,
  jump,
  onActiveSection,
  onProgress,
  onExplain,
  onCite,
  citeJump = null,
  onSelect,
  myHighlights,
  onMyHighlight,
  onHover,
  floating,
  onToast: _onToast,
  nudge,
}: Props) {
  const [html, setHtml] = useState<string | null>(null)
  const [isReal, setIsReal] = useState(false)
  const [failed, setFailed] = useState(false)
  /** 주입된 HTML 안에 React를 끼워 넣을 자리들 */
  const [slots, setSlots] = useState<{
    sparkles: Array<{ key: string; el: HTMLElement; label: string }>
    /** 그림 · 표 · 수식 */
    elements: Array<{ key: string; el: HTMLElement; label: string; tip: string; context: string }>
    config: HTMLElement | null
    memo: HTMLElement | null
  }>({ sparkles: [], elements: [], config: null, memo: null })

  const scrollRef = useRef<HTMLDivElement>(null)
  /* 이동 직후에는 관찰자가 다음 섹션으로 덮어쓰지 않게 잠깐 쉬어요 */
  const suppressUntil = useRef(0)
  const bodyRef = useRef<HTMLDivElement>(null)

  /* ── 본문 가져오기 ───────────────────────────────────────── */
  useEffect(() => {
    let alive = true
    setHtml(null)
    setFailed(false)
    loadPaperHtml(reader.paperId)
      .then((r) => {
        if (!alive) return
        setHtml(r.html)
        setIsReal(r.isReal)
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [reader.paperId])

  /* ── 주입 뒤 자리 찾기 + 하이라이트 칠하기 ───────────────── */
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return

    // 섹션 헤딩 옆 설명 버튼 자리
    const sparkles: Array<{ key: string; el: HTMLElement; label: string }> = []
    for (const sec of reader.sections) {
      if (!sec.htmlAnchor) continue
      const h = root.querySelector<HTMLElement>(`#${CSS.escape(sec.htmlAnchor)}`)
      if (!h) continue
      h.style.position = 'relative'
      const slot = document.createElement('span')
      slot.className = s.sparkleSlot!
      h.appendChild(slot)
      sparkles.push({
        key: sec.id,
        el: slot,
        label: `${sec.n ? sec.n + ' ' : ''}${sec.title} 설명 보기`,
      })
    }

    // 그림 · 표 · 수식 (arXiv LaTeXML) — 오른쪽 위에 설명 버튼
    const elements: Array<{ key: string; el: HTMLElement; label: string; tip: string; context: string }> = []
    const used = new Set<string>()
    let eqAuto = 0
    for (const box of Array.from(root.querySelectorAll<HTMLElement>('.ltx_figure, .ltx_table, .ltx_equationgroup, .ltx_equation'))) {
      if (box.classList.contains('ltx_equation') && box.closest('.ltx_equationgroup')) continue
      if (box.parentElement?.closest('.ltx_figure, .ltx_table')) continue // 그림 안의 작은 그림
      const isEq = !box.classList.contains('ltx_figure') && !box.classList.contains('ltx_table')
      const isTable = box.classList.contains('ltx_table')
      const caption = box.querySelector('.ltx_caption')?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
      const tag = isEq
        ? (box.querySelector('.ltx_tag_equation')?.textContent ?? '').trim()
        : (box.querySelector('.ltx_caption .ltx_tag')?.textContent ?? '').replace(/[:.]\s*$/, '').trim()
      const label = isEq ? (tag ? `식 ${tag}` : `${++eqAuto}번째 식`) : tag || (isTable ? '표' : '그림')
      if (used.has(label)) continue
      used.add(label)
      const tex = Array.from(box.querySelectorAll('math'))
        .map((m) => m.getAttribute('alttext') ?? '')
        .filter(Boolean)
        .join(' ')
      box.style.position = 'relative'
      const slot = document.createElement('span')
      slot.className = s.elementSlot!
      box.appendChild(slot)
      elements.push({
        key: `el:0:${label}`,
        el: slot,
        label,
        tip: isEq ? '수식 설명' : isTable ? '표 설명' : '그림 설명',
        context: (isEq ? tex : caption).slice(0, 600),
      })
    }

    setSlots({
      sparkles,
      elements,
      config: root.querySelector<HTMLElement>('#config-card'),
      memo: root.querySelector<HTMLElement>('#memo-fn4'),
    })

    return () => {
      sparkles.forEach((x) => x.el.remove())
      elements.forEach((x) => x.el.remove())
    }
  }, [html, reader.sections])

  /* ── 하이라이트: 켜고 끈 상태를 블록에 반영 ──────────────── */
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return
    // 먼저 전부 지워요 (블록 표시 · 글자 단위 mark)
    unmarkQuotes(root)
    root.querySelectorAll('[data-hl]').forEach((el) => el.removeAttribute('data-hl'))
    for (const h of reader.highlights) {
      if (!toggles[h.category]) continue
      if (h.htmlBlock) {
        // 샘플 골격 — 블록 단위
        const el = root.querySelector(`#${CSS.escape(h.htmlBlock)}`)
        if (el) el.setAttribute('data-hl', h.category)
      } else if (h.quote) {
        // vault 논문의 AI 분석 — 같은 구절을 본문 글자에서 찾아 그 글자만 칠해요
        markQuote(root, h.quote, h.category, h.id)
      }
    }
  }, [html, toggles, reader.highlights, isReal])

  /* ── 본문 안 버튼 (인용 칩·그림·수식) ────────────────────── */
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return
    const onClick = (e: Event) => {
      // arXiv 본문의 인용 링크(#bib.bib13) — 분석한 참고문헌에 그 번호가 있으면 인용 카드를 띄워요
      const bib = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#bib"]')
      if (bib) {
        const n = Number(bib.getAttribute('href')?.match(/bib(\d+)$/)?.[1])
        const scroller = scrollRef.current
        if (n && scroller && reader.references.some((r) => r.n === n)) {
          e.preventDefault()
          onCite(n, anchorFrom(bib, scroller))
          return
        }
        // 분석 전이면 본문 아래 참고문헌으로 옮겨 가요 (주소는 바꾸지 않고)
        const target = bodyRef.current?.querySelector<HTMLElement>(`#${CSS.escape((bib.getAttribute('href') ?? '').slice(1))}`)
        if (target) {
          e.preventDefault()
          target.scrollIntoView({ block: 'center' })
        }
        return
      }
      const t = (e.target as HTMLElement).closest<HTMLElement>('[data-cite],[data-explain]')
      if (!t) return
      const scroller = scrollRef.current
      if (!scroller) return
      const anchor = anchorFrom(t, scroller)
      const cite = t.dataset.cite
      if (cite) {
        onCite(Number(cite), anchor)
        return
      }
      if (t.dataset.explain) onExplain(t.dataset.explain, anchor)
    }
    const onMouseUp = () => {
      const scroller = scrollRef.current
      const sel = window.getSelection()
      if (!scroller || !sel || sel.isCollapsed) return
      const text = sel.toString().trim()
      if (text.length < 2) return
      const node = sel.anchorNode as HTMLElement | null
      if (!node || !root.contains(node)) return
      const sectionEl = (node.nodeType === 1 ? node : node.parentElement)?.closest<HTMLElement>(
        '[data-section]',
      )
      const range = sel.getRangeAt(0)
      const rect = range.getBoundingClientRect()
      const sectionId = sectionEl?.dataset.section ?? 'abs'
      const page = reader.sections.find((x) => x.id === sectionId)?.page ?? 1
      onSelect(anchorFromRect(rect, scroller), text, sectionId, {
        page,
        anchor: placeFromRange(range),
        boxes: null,
      })
    }

    const onOver = (e: Event) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>('[data-explain]')
      const scroller = scrollRef.current
      if (!scroller) return
      onHover(t?.dataset.explain ?? null, t ? anchorFrom(t, scroller) : null)
    }

    root.addEventListener('click', onClick)
    root.addEventListener('mouseup', onMouseUp)
    root.addEventListener('mouseover', onOver)
    return () => {
      root.removeEventListener('click', onClick)
      root.removeEventListener('mouseup', onMouseUp)
      root.removeEventListener('mouseover', onOver)
    }
  }, [html, onCite, onExplain, onSelect, onHover, reader.sections, reader.references])

  /*
   * ── vault 논문: PDF 목차 섹션 ↔ arXiv HTML 제목 잇기 ────────
   * 미리 만든 리더 데이터는 섹션마다 htmlAnchor가 있지만, vault 논문은 PDF 책갈피에서
   * 온 섹션이라 없어요. 제목 글자를 맞춰서 HTML 제목에 data-section을 붙여요.
   */
  // 어느 본문으로 만든 지도인지 같이 둬요 — 다 만들기 전에는 이동을 미뤄요
  const [mapped, setMapped] = useState<{ html: string | null; map: Record<string, string> }>({ html: null, map: {} })
  const anchors = mapped.map
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return
    const norm = (t: string) => t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '')
    const heads = Array.from(root.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')).map((h) => {
      const tag = h.querySelector('.ltx_tag')?.textContent ?? ''
      const text = h.textContent ?? ''
      return { el: h, key: norm(tag ? text.replace(tag, '') : text.replace(/^\s*(?:\d+|[A-Z])(?:\.\d+)*\.?\s+/, '')) }
    })
    const map: Record<string, string> = {}
    let from = 0
    for (const sec of reader.sections) {
      if (sec.htmlAnchor) continue
      const want = norm(sec.title)
      if (!want) continue
      // 순서대로 찾아요 — 같은 제목이 뒤에 또 있어도(부록 등) 앞에서부터
      let i = heads.findIndex((h, j) => j >= from && h.key === want)
      if (i < 0) i = heads.findIndex((h, j) => j >= from && want.length >= 6 && (h.key.startsWith(want) || want.startsWith(h.key)) && h.key.length >= 6)
      if (i < 0) continue
      from = i + 1
      const h = heads[i]!.el
      if (!h.id) h.id = `lr-${sec.id}`
      h.dataset.section = sec.id
      map[sec.id] = h.id
    }
    setMapped({ html, map })
  }, [html, reader.sections])

  /* ── 스크롤 추적 ─────────────────────────────────────────── */
  useEffect(() => {
    const root = scrollRef.current
    const body = bodyRef.current
    if (!root || !body || !html) return

    const marks = Array.from(body.querySelectorAll<HTMLElement>('[data-section]'))
    const io = new IntersectionObserver(
      () => {
        if (Date.now() < suppressUntil.current) return
        const rootTop = root.getBoundingClientRect().top
        const passed = marks.filter((el) => el.getBoundingClientRect().top - rootTop <= 90)
        const last = passed[passed.length - 1]
        if (last?.dataset.section) onActiveSection(last.dataset.section)
      },
      { root, rootMargin: '-90px 0px 0px 0px', threshold: 0 },
    )
    marks.forEach((m) => io.observe(m))
    return () => io.disconnect()
  }, [html, onActiveSection, anchors])

  const reportProgress = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const max = el.scrollHeight - el.clientHeight
    if (max <= 4) return
    // 소수점 높이 때문에 끝에서 99%로 멈추는 걸 막아요
    const pct = el.scrollTop >= max - 2 ? 100 : Math.round((el.scrollTop / max) * 100)
    onProgress(pct)
  }, [onProgress])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !html) return
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        reportProgress()
      })
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    const ro = new ResizeObserver(onScroll)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    reportProgress()
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
      if (frame) cancelAnimationFrame(frame)
    }
  }, [html, reportProgress])

  /* ── 이동 ────────────────────────────────────────────────── */
  const scrollToSection = useCallback(
    (sectionId: string, smooth = true) => {
      const root = scrollRef.current
      const body = bodyRef.current
      if (!root || !body) return
      const sec = reader.sections.find((x) => x.id === sectionId)
      const anchor = sec?.htmlAnchor ?? anchors[sectionId]
      if (!anchor) return
      const el = body.querySelector<HTMLElement>(`#${CSS.escape(anchor)}`)
      if (!el) return
      // offsetTop은 offsetParent 기준이라 어긋나요. 화면 좌표로 계산해요.
      const top =
        el.getBoundingClientRect().top -
        root.getBoundingClientRect().top +
        root.scrollTop -
        18
      suppressUntil.current = Date.now() + (smooth ? 700 : 300)
      root.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' })
    },
    [reader.sections, anchors],
  )

  // PDF에서 넘어오면 본문이 아직 없을 수 있어요.
  // 본문이 붙은 뒤에도 한 번 맞춰 줘야 읽던 자리가 유지돼요.
  const appliedJump = useRef<number | null>(null)
  useEffect(() => {
    if (!html || !jump || mapped.html !== html) return
    if (appliedJump.current === jump.nonce) return
    appliedJump.current = jump.nonce
    // 주입 직후에는 레이아웃이 아직이라 한 프레임 뒤에 옮겨요
    requestAnimationFrame(() => {
      const root = scrollRef.current
      const mark = jump.highlightId ? bodyRef.current?.querySelector<HTMLElement>(`[data-hl-id="${CSS.escape(jump.highlightId)}"]`) : null
      if (root && mark) {
        const top = mark.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 120
        suppressUntil.current = Date.now() + 300
        root.scrollTo({ top: Math.max(0, top), behavior: 'auto' })
        mark.animate?.([{ outline: '2px solid var(--accent)' }, { outline: '2px solid transparent' }], { duration: 1400 })
        return
      }
      if (jump.sectionId) scrollToSection(jump.sectionId, false)
    })
  }, [html, jump, scrollToSection, mapped.html])

  /* ── 인용 탭에서 제목을 누르면: 본문 인용 링크로 가서 인용 카드를 열어요 ── */
  // 보기를 바꿔 새로 열렸을 때 지난 요청을 다시 하지 않게, 처음 값은 이미 한 것으로 봐요
  const appliedCite = useRef<number | null>(citeJump?.nonce ?? null)
  useEffect(() => {
    const root = scrollRef.current
    const body = bodyRef.current
    if (!html || !citeJump || !root || !body || appliedCite.current === citeJump.nonce) return
    appliedCite.current = citeJump.nonce
    const n = citeJump.n
    const links = Array.from(body.querySelectorAll<HTMLElement>('a[href^="#bib"], [data-cite]')).filter((el) => {
      if (el.closest('.ltx_bibliography')) return false
      const got = el.dataset.cite ?? el.getAttribute('href')?.match(/bib(\d+)$/)?.[1]
      return Number(got) === n
    })
    // 본문 인용이 없으면 참고문헌 목록의 그 항목으로
    const target = links.length ? links[citeJump.k % links.length] : body.querySelector<HTMLElement>(`#${CSS.escape(`bib.bib${n}`)}`)
    if (!target) {
      onCite(n, { x: 40, y: root.scrollTop + 40, width: 0 })
      return
    }
    // 바로 옮겨요 — 부드럽게 옮기면 그사이 그림이 로드되며 자리가 밀려 중간에 멈춰요
    const top = target.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - root.clientHeight / 4
    suppressUntil.current = Date.now() + 400
    root.scrollTo({ top: Math.max(0, top), behavior: 'auto' })
    target.animate?.([{ background: 'var(--accent-tint)' }, { background: 'transparent' }], { duration: 1600 })
    // 옮긴 뒤 자리가 정해지면 카드를 열어요
    requestAnimationFrame(() => onCite(n, anchorFrom(target, root)))
  }, [citeJump?.nonce, html]) // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) {
    return (
      <div className={s.view}>
        <p className={s.failed}>본문을 불러오지 못했어요.</p>
      </div>
    )
  }

  return (
    <div className={s.view}>
      <div className={s.scroll} ref={scrollRef}>
        {!isReal && html && (
          <div className={s.sampleBar}>
            구조만 있는 샘플 HTML이에요 · 실제 본문을 보려면
            <span className={s.sampleMono}>web/fixtures/{reader.paperId}.arxiv.html</span>
            파일을 넣어 주세요
          </div>
        )}

        {html === null ? (
          <p className={s.loading}>본문을 불러오는 중이에요…</p>
        ) : (
          <div
            ref={bodyRef}
            // arXiv 본문은 <article class="ltx_document">라 논문 글꼴 · 폭을 바깥에서 입혀요
            className={isReal ? 'paper' : undefined}
            // loadPaperHtml이 DOMPurify로 정리한 결과만 들어와요
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}

        {/* 내가 칠한 하이라이트를 블록 id + 오프셋으로 되살려 그려요 */}
        <MyHighlightLayer
          bodyRef={bodyRef}
          scrollRef={scrollRef}
          annotations={myHighlights}
          revision={html}
          onPick={(annotation, rect) => {
            const scroller = scrollRef.current
            if (scroller) onMyHighlight(annotation, anchorFromRect(rect, scroller))
          }}
        />

        {/* 주입된 HTML 안에 React 조각을 끼워 넣어요 */}
        {slots.sparkles.map((x) =>
          createPortal(
            <Sparkle
              label={x.label}
              onClick={(el) => {
                const scroller = scrollRef.current
                if (scroller) onExplain(x.key, anchorFrom(el, scroller))
              }}
              onHover={(el) => {
                const scroller = scrollRef.current
                onHover(el && scroller ? x.key : null, el && scroller ? anchorFrom(el, scroller) : null)
              }}
            />,
            x.el,
          ),
        )}
        {slots.elements.map((x) =>
          createPortal(
            <Sparkle
              label={`${x.label} 설명 보기`}
              tip={x.tip}
              onClick={(el) => {
                const scroller = scrollRef.current
                if (scroller) onExplain(x.key, anchorFrom(el, scroller), x.context)
              }}
              onHover={(el) => {
                const scroller = scrollRef.current
                onHover(el && scroller ? x.key : null, el && scroller ? anchorFrom(el, scroller) : null)
              }}
            />,
            x.el,
          ),
        )}
        {slots.config &&
          createPortal(
            <ConfigCard
              data={reader.extractedConfig}
              onJump={(sectionId) => scrollToSection(sectionId)}
            />,
            slots.config,
          )}
        {slots.memo &&
          createPortal(
            <MemoCard data={reader.inlineMemo} paperId={reader.paperId} />,
            slots.memo,
          )}

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

/** 수식 LaTeX 복사는 PDF 보기와 같은 동작을 써요 */
export async function copyLatex(latex: string, onToast: (m: string) => void) {
  await copyText(latex)
  onToast('LaTeX를 복사했어요')
}

/* ── AI 하이라이트 구절을 HTML 글자에서 찾기 ─────────────────── */

/**
 * PDF에서 옮긴 구절과 arXiv HTML 글자는 공백 · 하이픈 · 합자(ﬁ) · 수식 표기가 달라요.
 * 그래서 글자와 숫자만 남겨(소문자) 비교하고, 찾은 자리의 원래 글자를 감싸요.
 */
const keyOf = (t: string) => t.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')

function unmarkQuotes(root: HTMLElement) {
  root.querySelectorAll('mark[data-hl-id]').forEach((m) => {
    const parent = m.parentNode
    if (!parent) return
    while (m.firstChild) parent.insertBefore(m.firstChild, m)
    parent.removeChild(m)
    parent.normalize()
  })
}

function markQuote(root: HTMLElement, quote: string, category: string, id: string) {
  const want = keyOf(quote)
  if (want.length < 12) return
  // 본문 글자 — 각주 본문 · 수식 원문(annotation) · 끼워 넣은 버튼은 빼요
  const nodes: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      (n.parentElement?.closest('.ltx_note_outer, annotation, annotation-xml, button, script, style') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  })
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  let key = ''
  const at: Array<[number, number]> = [] // key 글자마다 (노드 번호, 노드 안 위치)
  nodes.forEach((n, ni) => {
    const t = n.data
    for (let i = 0; i < t.length; i++) {
      const k = keyOf(t[i]!)
      for (const ch of k) {
        key += ch
        at.push([ni, i])
      }
    }
  })
  let start = key.indexOf(want)
  let len = want.length
  if (start < 0 && want.length > 40) {
    // 끝쪽 표기가 달라도 앞부분으로 찾아요
    start = key.indexOf(want.slice(0, 40))
    len = Math.min(want.length, key.length - start)
  }
  if (start < 0) return
  const [n0, o0] = at[start]!
  const [n1, o1] = at[start + len - 1]!
  for (let ni = n1; ni >= n0; ni--) {
    const node = nodes[ni]!
    const a = ni === n0 ? o0 : 0
    const b = ni === n1 ? o1 + 1 : node.data.length
    if (b <= a || !node.data.slice(a, b).trim()) continue
    // [a, b)만 떼어 mark로 감싸요 (뒤에서부터 해야 앞 위치가 안 바뀌어요)
    const mid = a > 0 ? node.splitText(a) : node
    mid.splitText(b - a)
    const mark = document.createElement('mark')
    mark.dataset.hl = category
    mark.dataset.hlId = id
    mid.parentNode?.insertBefore(mark, mid)
    mark.appendChild(mid)
  }
}
