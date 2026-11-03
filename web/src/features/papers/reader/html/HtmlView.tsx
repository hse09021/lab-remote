import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { PaperReaderPayload } from '@/api/types'
import { Button } from '@/components'
import { copyText } from '@/lib/clipboard'
import type { HighlightToggles } from '../highlightCategories'
import { anchorFrom, anchorFromRect } from '../floating/useReaderOverlays'
import type { SelectionAnchor as Anchor } from '../floating/SelectionMenu'
import { loadPaperHtml } from './loadPaperHtml'
import { CheckNote, ConfigCard, MemoCard } from './blocks'
import { Sparkle } from './Sparkle'
import s from './HtmlView.module.css'
import '@/styles/paper.css'

export interface HtmlJump {
  sectionId: string
  nonce: number
}

interface Props {
  reader: PaperReaderPayload
  toggles: HighlightToggles
  jump: HtmlJump | null
  onActiveSection: (id: string) => void
  onProgress: (pct: number) => void
  /** 설명 버튼·그림·수식 — 누른 자리를 함께 넘겨요 */
  onExplain: (key: string, anchor: Anchor) => void
  /** 본문 인용 칩 */
  onCite: (n: number, anchor: Anchor) => void
  /** 실제 드래그 선택 */
  onSelect: (anchor: Anchor, text: string, sectionId: string) => void
  onHover: (key: string | null, anchor: Anchor | null) => void
  floating: ReactNode
  onToast: (msg: string) => void
  /** 수치 불일치에서 고른 재현 기준 */
  target: string | null
  onTargetChange: (value: string) => void
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
  onSelect,
  onHover,
  floating,
  onToast,
  target,
  onTargetChange,
  nudge,
}: Props) {
  const [html, setHtml] = useState<string | null>(null)
  const [isReal, setIsReal] = useState(false)
  const [failed, setFailed] = useState(false)
  /** 주입된 HTML 안에 React 를 끼워 넣을 자리들 */
  const [slots, setSlots] = useState<{
    sparkles: Array<{ key: string; el: HTMLElement; label: string }>
    config: HTMLElement | null
    check: HTMLElement | null
    memo: HTMLElement | null
  }>({ sparkles: [], config: null, check: null, memo: null })

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
        label: `${sec.n ? sec.n + ' ' : ''}${sec.title} 설명받기`,
      })
    }

    setSlots({
      sparkles,
      config: root.querySelector<HTMLElement>('#config-card'),
      check: root.querySelector<HTMLElement>('#note-check'),
      memo: root.querySelector<HTMLElement>('#memo-fn4'),
    })

    return () => {
      sparkles.forEach((x) => x.el.remove())
    }
  }, [html, reader.sections])

  /* ── 하이라이트: 켜고 끈 상태를 블록에 반영 ──────────────── */
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return
    // 먼저 전부 지워요
    root.querySelectorAll('[data-hl]').forEach((el) => el.removeAttribute('data-hl'))
    for (const h of reader.highlights) {
      if (!toggles[h.category] || !h.htmlBlock) continue
      const el = root.querySelector(`#${CSS.escape(h.htmlBlock)}`)
      // 샘플 골격은 블록 단위예요. 글자 단위는 실제 arXiv HTML 일 때만 써요
      if (el) el.setAttribute('data-hl', h.category)
    }
  }, [html, toggles, reader.highlights, isReal])

  /* ── 본문 안 버튼 (인용 칩·그림·수식) ────────────────────── */
  useEffect(() => {
    const root = bodyRef.current
    if (!root || !html) return
    const onClick = (e: Event) => {
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
      const rect = sel.getRangeAt(0).getBoundingClientRect()
      onSelect(anchorFromRect(rect, scroller), text, sectionEl?.dataset.section ?? 'abs')
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
  }, [html, onCite, onExplain, onSelect, onHover])

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
  }, [html, onActiveSection])

  const reportProgress = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const max = el.scrollHeight - el.clientHeight
    if (max <= 4) return
    // 소수점 높이 때문에 끝에서 99% 로 멈추는 걸 막아요
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
      if (!sec?.htmlAnchor) return
      const el = body.querySelector<HTMLElement>(`#${CSS.escape(sec.htmlAnchor)}`)
      if (!el) return
      // offsetTop 은 offsetParent 기준이라 어긋나요. 화면 좌표로 계산해요.
      const top =
        el.getBoundingClientRect().top -
        root.getBoundingClientRect().top +
        root.scrollTop -
        18
      suppressUntil.current = Date.now() + (smooth ? 700 : 300)
      root.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' })
    },
    [reader.sections],
  )

  // PDF 에서 넘어오면 본문이 아직 없을 수 있어요.
  // 본문이 붙은 뒤에도 한 번 맞춰 줘야 읽던 자리가 유지돼요.
  const appliedJump = useRef<number | null>(null)
  useEffect(() => {
    if (!html || !jump) return
    if (appliedJump.current === jump.nonce) return
    appliedJump.current = jump.nonce
    // 주입 직후에는 레이아웃이 아직이라 한 프레임 뒤에 옮겨요
    requestAnimationFrame(() => scrollToSection(jump.sectionId, false))
  }, [html, jump, scrollToSection])

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
            구조만 담은 샘플 골격이에요 · 실제 본문을 보려면
            <span className={s.sampleMono}>web/fixtures/{reader.paperId}.arxiv.html</span>
            을 두세요
          </div>
        )}

        {html === null ? (
          <p className={s.loading}>본문을 불러오는 중이에요…</p>
        ) : (
          <div
            ref={bodyRef}
            // loadPaperHtml 이 DOMPurify 로 정리한 결과만 들어와요
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}

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
        {slots.config &&
          createPortal(
            <ConfigCard
              data={reader.extractedConfig}
              onJump={(sectionId) => scrollToSection(sectionId)}
            />,
            slots.config,
          )}
        {slots.check &&
          createPortal(
            <CheckNote
              data={reader.discrepancy}
              target={target}
              onPick={onTargetChange}
            />,
            slots.check,
          )}
        {slots.memo &&
          createPortal(
            <MemoCard
              data={reader.inlineMemo}
              onEdit={() => onToast('메모 수정은 다음 단계에서 붙여요')}
            />,
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
