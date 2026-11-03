import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { designDraftQuery, useSaveDesignValues } from '@/api/design'
import { paperReaderQuery } from '@/api/papers'
import type { DesignDraft, DesignOption, DesignValue } from '@/api/types'
import { Button, Resizer, Skeleton, Toast, VisuallyHidden } from '@/components'
import { usePaneResize } from '@/lib/usePaneResize'
import { useToast } from '@/lib/useToast'
import s from './ExperimentDesignDraft.module.css'
import { useIsMobile } from '@/lib/useMediaQuery'
import { MobileDesignDraft } from '../mobile/MobileDesignDraft'

/** 값이 어디서 왔는지 */
type ValueSource = 'paper' | 'reader' | 'typed'

/** 논문을 안 고르고 들어오면 리더가 있는 논문으로 시작해요 */
const DEFAULT_PAPER = 'attn'

export default function ExperimentDesignDraft() {
  const isMobile = useIsMobile()
  if (isMobile) return <MobileDesignDraft />

  const [params] = useSearchParams()
  const paperId = params.get('paper') ?? DEFAULT_PAPER

  const draft = useQuery(designDraftQuery(paperId))
  // 재현 목표는 리더에서 고른 값을 그대로 써요
  const reader = useQuery({ ...paperReaderQuery(paperId), retry: false })

  if (draft.isPending) return <DraftSkeleton />
  if (draft.isError || !draft.data) {
    return (
      <div className={s.page}>
        <p className={s.failed}>이 논문의 설계 초안을 불러오지 못했어요.</p>
      </div>
    )
  }

  return (
    <DraftBody
      paperId={paperId}
      data={draft.data}
      readerTarget={reader.data?.discrepancy.chosen ?? null}
    />
  )
}

function DraftBody({
  paperId,
  data,
  readerTarget,
}: {
  paperId: string
  data: DesignDraft
  readerTarget: string | null
}) {
  const navigate = useNavigate()
  const toast = useToast()
  const chat = usePaneResize({ initial: 420, min: 320, max: 640, dir: -1, collapsible: true })
  const saveValues = useSaveDesignValues(paperId)

  const [start, setStart] = useState('repro')
  const [env, setEnv] = useState('reuse')
  /** 아직 저장하지 않은 입력 */
  const [edits, setEdits] = useState<Record<string, string>>({})

  /**
   * 값이 어디서 왔는지 — 저장해 둔 값 → 지금 친 값 순으로 덮어요.
   * 재현 목표는 리더에서 고른 값을 가져와요.
   */
  const valueOf = (v: DesignValue): { text: string; from: ValueSource } => {
    if (edits[v.key] !== undefined) return { text: edits[v.key], from: 'typed' }
    const saved = data.saved?.[v.key]
    if (saved !== undefined) return { text: saved, from: 'typed' }
    if (v.kind === 'fromReader' && readerTarget) return { text: readerTarget, from: 'reader' }
    return { text: v.value ?? '', from: 'paper' }
  }

  const rows = useMemo(
    () => data.values.map((v) => ({ value: v, ...valueOf(v) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.values, data.saved, edits, readerTarget],
  )

  // 목업은 "원문 확인 7 / 추정 필요 2"가 마크업에 박혀 있었어요. 여기서는 세요
  const confirmed = rows.filter((r) => r.value.kind === 'confirmed').length
  const missing = rows.filter((r) => r.value.kind !== 'confirmed' && !r.text.trim())
  const canCreate = missing.length === 0
  const dirty = Object.keys(edits).length > 0

  const spec = data.spec.map((row) =>
    row.label === '환경' ? row : row,
  )

  return (
    <div className={s.page}>
      <ContextBar title={data.paperTitle} paperId={paperId} />

      <div className={s.canvas}>
        <section aria-label="설계 초안" className={s.main}>
          <div className={s.scroll}>
            <section aria-label="추출한 값" className={s.block}>
              <div className={s.blockHead}>
                <h2 className={s.h2}>추출한 값</h2>
                <div className={s.counts}>
                  <span className={s.countOk}>원문 확인 {confirmed}</span>
                  <span className={s.countWarn}>추정 필요 {missing.length}</span>
                </div>
              </div>

              <div className={s.tableWrap}>
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th className={s.thItem}>항목</th>
                      <th className={s.thValue}>값</th>
                      <th className={s.thRef}>근거</th>
                      <th className={s.thState}>상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(({ value: v, text, from }) => (
                      <ValueRow
                        key={v.key}
                        value={v}
                        text={text}
                        from={from}
                        onChange={(next) => setEdits((prev) => ({ ...prev, [v.key]: next }))}
                        onEvidence={() =>
                          v.evidence &&
                          navigate(`/papers/${paperId}?section=${v.evidence.sectionId}`)
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section aria-label="실험 설계" className={s.block}>
              <h2 className={s.h2}>실험 설계</h2>
              <dl className={s.spec}>
                {spec.map((row) => (
                  <div key={row.label} className={s.specRow}>
                    <dt className={s.specLabel}>{row.label}</dt>
                    <dd className={s.specValue}>{row.value}</dd>
                  </div>
                ))}
                <div className={s.specRow}>
                  <dt className={s.specLabel}>환경</dt>
                  <dd className={s.specValue}>{data.envLabels[env] ?? env}</dd>
                </div>
              </dl>
            </section>

            <section aria-label="생성될 파일" className={s.block}>
              <div className={s.blockHead}>
                <h2 className={s.h2}>생성될 파일</h2>
                <span className={s.blockNote}>{data.filesNote}</span>
              </div>
              <div className={s.files}>
                {data.files.map((f) => (
                  <span key={f} className={s.file}>
                    {f}
                  </span>
                ))}
              </div>
            </section>
          </div>

          <div className={s.footer}>
            <span className={s.footerText}>
              {canCreate ? (
                <>값이 모두 찼어요 · 프로젝트를 생성할 수 있어요</>
              ) : (
                <>
                  <span className={s.footerWarn}>추정 필요 {missing.length}개</span>가 남았어요 ·{' '}
                  {missing.map((m) => m.value.item).join(', ')} 값을 넣으면 생성할 수 있어요
                </>
              )}
            </span>
            <Button
              variant="outline"
              size="md"
              disabled={!dirty || saveValues.isPending}
              onClick={() => {
                saveValues.mutate({ ...(data.saved ?? {}), ...edits })
                setEdits({})
                toast.show('초안을 저장했어요')
              }}
            >
              초안 저장
            </Button>
            <Button
              variant="primary"
              size="md"
              padWide
              disabled={!canCreate}
              onClick={() => {
                saveValues.mutate({ ...(data.saved ?? {}), ...edits })
                // 토스트는 옮겨 간 화면에서 띄워요 (여기서 띄우면 같이 사라져요)
                navigate('/experiments', {
                  state: { toast: '목업이라 실제 생성은 아직이에요 · 대시보드로 왔어요' },
                })
              }}
            >
              프로젝트 생성
            </Button>
          </div>
        </section>

        <Resizer handle={chat.resizerProps} label="설계 토론 패널 너비 조절" />

        {chat.closed ? (
          <button
            type="button"
            aria-label="설계 토론 패널 펼치기"
            onClick={chat.toggle}
            className={s.chatRail}
          >
            토론
          </button>
        ) : (
          <DesignChatPanel
            style={chat.style}
            data={data}
            start={start}
            env={env}
            onStart={setStart}
            onEnv={setEnv}
            onCollapse={chat.toggle}
            onToast={toast.show}
          />
        )}
      </div>

      <Toast message={toast.message} action={toast.action} />
    </div>
  )
}

/* ── 값 한 줄 ─────────────────────────────────────────────── */

function ValueRow({
  value: v,
  text,
  from,
  onChange,
  onEvidence,
}: {
  value: DesignValue
  text: string
  from: ValueSource
  onChange: (next: string) => void
  onEvidence: () => void
}) {
  const filled = !!text.trim()
  const needsInput = v.kind !== 'confirmed'
  const state = !needsInput
    ? '원문 확인'
    : !filled
      ? '추정 필요'
      : from === 'reader'
        ? '리더에서'
        : '직접 넣음'
  const inputId = `design-${v.key}`

  return (
    <tr data-warn={needsInput && !filled ? 'true' : undefined} className={s.row}>
      <td className={s.tdItem}>{v.item}</td>
      <td className={s.tdValue}>
        {needsInput ? (
          <>
            <VisuallyHidden>
              <label htmlFor={inputId}>{v.item} 값</label>
            </VisuallyHidden>
            <input
              id={inputId}
              type="text"
              value={text}
              placeholder={v.hint ?? '직접 입력'}
              onChange={(e) => onChange(e.target.value)}
              data-warn={filled ? undefined : 'true'}
              className={s.input}
            />
          </>
        ) : (
          <span className={s.mono}>{text}</span>
        )}
      </td>
      <td className={s.tdRef}>
        {v.evidence ? (
          <button type="button" onClick={onEvidence} className={s.evidence}>
            {v.evidence.label} ↗
          </button>
        ) : (
          <span className={s.noRef}>없음</span>
        )}
      </td>
      <td className={s.tdState}>
        <span data-state={state} className={s.state}>
          {state}
        </span>
      </td>
    </tr>
  )
}

/* ── Claude와 설계 토론 ───────────────────────────────────── */

function DesignChatPanel({
  style,
  data,
  start,
  env,
  onStart,
  onEnv,
  onCollapse,
  onToast,
}: {
  style: React.CSSProperties
  data: DesignDraft
  start: string
  env: string
  onStart: (id: string) => void
  onEnv: (id: string) => void
  onCollapse: () => void
  onToast: (msg: string) => void
}) {
  const [draft, setDraft] = useState('')

  return (
    <aside aria-label="Claude와 설계 토론" style={style} className={s.chat}>
      <div className={s.chatHead}>
        <span className={s.chatTitle}>Claude와 설계 토론</span>
        <span className={s.chatConn}>
          <span className={s.dot} />
          연결됨
        </span>
        <button
          type="button"
          aria-label="설계 토론 패널 접기"
          onClick={onCollapse}
          className={s.collapse}
        >
          ›
        </button>
      </div>

      <div className={s.chatBody}>
        {data.chat.map((block, i) => {
          if (block.kind === 'user') {
            return (
              <div key={i} className={s.userBubble}>
                {block.text}
              </div>
            )
          }
          if (block.kind === 'assistant') {
            return (
              <p key={i} className={s.assistant}>
                {block.text}
              </p>
            )
          }
          const isStart = block.options === 'startOptions'
          const options: DesignOption[] = isStart ? data.startOptions : data.envOptions
          const picked = isStart ? start : env
          const pick = isStart ? onStart : onEnv
          return (
            <div key={i} className={s.choiceCard}>
              <span className={s.choiceTitle}>{block.title}</span>
              {options.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  aria-pressed={picked === o.id}
                  onClick={() => pick(o.id)}
                  className={s.choice}
                >
                  <span className={s.radio} />
                  <span className={s.choiceText}>
                    <span className={s.choiceLabel}>{o.label}</span>
                    <span className={s.choiceDesc}>{o.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          )
        })}
      </div>

      <div className={s.composerWrap}>
        <div className={s.composer}>
          <VisuallyHidden>
            <label htmlFor="design-chat">설계에 대해 말하기</label>
          </VisuallyHidden>
          <textarea
            id="design-chat"
            rows={2}
            value={draft}
            placeholder="설계에 대해 말하기 · 예: accumulation은 8로 해줘"
            onChange={(e) => setDraft(e.target.value)}
            className={s.textarea}
          />
          <div className={s.composerRow}>
            <span className={s.attachment}>{data.attachment}</span>
            <button
              type="button"
              aria-label="보내기"
              onClick={() => {
                setDraft('')
                onToast('목업이라 실제 답변은 연결돼 있지 않아요')
              }}
              className={s.send}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 19V5M6 11l6-6 6 6" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}

/* ── 맨 위 줄 ─────────────────────────────────────────────── */

function ContextBar({ title, paperId }: { title: string; paperId: string }) {
  const navigate = useNavigate()
  return (
    <div className={s.contextBar}>
      <div className={s.contextLeft}>
        <button
          type="button"
          aria-label="논문 리더로 돌아가기"
          onClick={() => navigate(`/papers/${paperId}`)}
          className={s.back}
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <div className={s.contextTitle}>
          <h1 className={s.h1}>실험 설계 초안</h1>
          <span className={s.contextMeta}>기준 논문 · {title}</span>
        </div>
      </div>
      <Stepper />
    </div>
  )
}

function Stepper() {
  return (
    <ol aria-label="진행 단계" className={s.steps}>
      <li className={s.stepDone}>
        <span className={s.stepMark}>✓</span>값 추출
      </li>
      <li aria-hidden="true" className={s.stepLine} />
      <li aria-current="step" className={s.stepNow}>
        <span className={s.stepNumNow}>2</span>검토·설계
      </li>
      <li aria-hidden="true" className={s.stepLine} />
      <li className={s.stepNext}>
        <span className={s.stepNum}>3</span>프로젝트 생성
      </li>
    </ol>
  )
}

function DraftSkeleton() {
  return (
    <div className={s.page}>
      <div className={s.contextBar}>
        <Skeleton width={240} height={24} />
      </div>
      <div className={s.canvas}>
        <div className={s.scroll}>
          <Skeleton width="60%" height={20} />
          <Skeleton width="100%" height={200} />
        </div>
      </div>
    </div>
  )
}
