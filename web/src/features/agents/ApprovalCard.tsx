import { useState } from 'react'
import { useAnswer } from '@/api/agents'
import type { PendingApproval } from '@/api/agents'
import { ApiError } from '@/api/client'
import s from './Agents.module.css'
import { WarningIcon } from '@/components/icons'

/** diff 한 줄 */
interface Line {
  sign: '+' | '-' | ' '
  code: string
}

const MAX_LINES = 400

function lines(text: unknown, sign: Line['sign']): Line[] {
  return String(text ?? '')
    .split('\n')
    .map((code) => ({ sign, code }))
}

/** 도구 입력을 사람이 볼 모양으로. Edit·Write는 diff, Bash는 명령, 나머지는 JSON. */
export function approvalBody(tool: string, input: Record<string, unknown>): { kind: 'diff'; lines: Line[]; file: string } | { kind: 'text'; text: string } {
  const file = String(input.file_path ?? input.notebook_path ?? '')
  if (tool === 'Edit') {
    return { kind: 'diff', file, lines: [...lines(input.old_string, '-'), ...lines(input.new_string, '+')].slice(0, MAX_LINES) }
  }
  if (tool === 'MultiEdit' && Array.isArray(input.edits)) {
    const out: Line[] = []
    for (const e of input.edits as Record<string, unknown>[]) {
      out.push(...lines(e.old_string, '-'), ...lines(e.new_string, '+'), { sign: ' ', code: '···' })
    }
    return { kind: 'diff', file, lines: out.slice(0, MAX_LINES) }
  }
  if (tool === 'Write') return { kind: 'diff', file, lines: lines(input.content, '+').slice(0, MAX_LINES) }
  if (tool === 'Bash') {
    const desc = input.description ? `# ${String(input.description)}\n` : ''
    return { kind: 'text', text: `${desc}$ ${String(input.command ?? '')}` }
  }
  if (tool === 'ExitPlanMode') return { kind: 'text', text: String(input.plan ?? '') }
  return { kind: 'text', text: JSON.stringify(input, null, 2) }
}

export function DiffView({ tool, input }: { tool: string; input: Record<string, unknown> }) {
  const body = approvalBody(tool, input)
  if (body.kind === 'text') return <pre className={s.codeBlock}>{body.text}</pre>
  const add = body.lines.filter((l) => l.sign === '+').length
  const del = body.lines.filter((l) => l.sign === '-').length
  return (
    <div className={s.diff}>
      <div className={s.diffHead}>
        <span className={s.mono}>{body.file}</span>
        <span className={s.add}>+{add}</span>
        <span className={s.del}>−{del}</span>
      </div>
      <div className={s.diffBody}>
        {body.lines.map((l, i) => (
          <div key={i} className={s.diffLine} data-sign={l.sign}>
            <span aria-hidden="true" className={s.diffSign}>
              {l.sign}
            </span>
            <span>{l.code || ' '}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const ago = (sec: number) => {
  const d = Math.max(0, Date.now() / 1000 - sec)
  if (d < 60) return '방금부터'
  if (d < 3600) return `${Math.floor(d / 60)}분 전부터`
  return `${Math.floor(d / 3600)}시간 전부터`
}

interface Question {
  question: string
  header?: string
  options?: { label: string; description?: string }[]
  multiSelect?: boolean
}

/** Claude의 객관식 질문(AskUserQuestion) — 보기를 고르거나 직접 적어서 답해요 */
export function QuestionCard({ p, via }: { p: PendingApproval; via: string }) {
  const answer = useAnswer()
  const questions = (Array.isArray(p.input.questions) ? p.input.questions : []) as Question[]
  const [picked, setPicked] = useState<Record<string, string[]>>({})
  const [other, setOther] = useState<Record<string, string>>({})
  const [response, setResponse] = useState('')
  const err = answer.error instanceof ApiError ? answer.error.message : answer.error ? String(answer.error) : ''

  const toggle = (q: Question, label: string) =>
    setPicked((old) => {
      const cur = old[q.question] ?? []
      if (!q.multiSelect) return { ...old, [q.question]: [label] }
      return { ...old, [q.question]: cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label] }
    })

  const submit = () => {
    const answers: Record<string, string | string[]> = {}
    for (const q of questions) {
      // "기타"에 적은 글은 'Other'가 아니라 그 글 자체를 답으로 (문서: user-input)
      const labels = [...(picked[q.question] ?? []), ...(other[q.question]?.trim() ? [other[q.question].trim()] : [])]
      if (labels.length) answers[q.question] = q.multiSelect ? labels : labels[labels.length - 1]
    }
    answer.mutate({ id: p.id, choice: 'answer', answers, response, via })
  }

  return (
    <div role="group" aria-label="에이전트의 질문" className={s.approval}>
      <div className={s.approvalHead}>
        <span className={s.approvalTitle}>질문이 왔어요</span>
        <span className={s.muted}>{ago(p.createdAt)} 기다리는 중</span>
      </div>
      {questions.map((q) => (
        <fieldset key={q.question} className={s.question}>
          <legend className={s.questionText}>
            {q.header && <span className={s.questionHeader}>{q.header}</span>}
            {q.question}
            {q.multiSelect && <span className={s.muted}> · 여러 개 선택할 수 있어요</span>}
          </legend>
          <div className={s.options}>
            {(q.options ?? []).map((o) => {
              const on = (picked[q.question] ?? []).includes(o.label)
              return (
                <button
                  key={o.label}
                  type="button"
                  role={q.multiSelect ? 'checkbox' : 'radio'}
                  aria-checked={on}
                  className={s.option}
                  onClick={() => toggle(q, o.label)}
                >
                  <span className={s.optionLabel}>{o.label}</span>
                  {o.description && <span className={s.menuDesc}>{o.description}</span>}
                </button>
              )
            })}
          </div>
          <input
            className={s.reason}
            value={other[q.question] ?? ''}
            onChange={(e) => setOther((old) => ({ ...old, [q.question]: e.target.value }))}
            placeholder="기타 — 직접 입력"
            aria-label={`${q.question} — 기타`}
          />
        </fieldset>
      ))}
      <input
        className={s.reason}
        value={response}
        onChange={(e) => setResponse(e.target.value)}
        placeholder="선택지 대신 직접 답하기 (선택)"
        aria-label="선택지 대신 직접 답하기"
      />
      <div className={s.approvalActions}>
        <button type="button" className={s.allow} disabled={answer.isPending} onClick={submit}>
          답하기
        </button>
        <button
          type="button"
          className={s.denyBtn}
          disabled={answer.isPending}
          onClick={() => answer.mutate({ id: p.id, choice: 'deny', reason: '질문에 답하지 않았어요', via })}
        >
          건너뛰기
        </button>
        <span className={s.muted}>같은 질문이 Dashboard와 Inbox에도 표시돼요. 먼저 답한 곳의 답이 적용돼요.</span>
      </div>
      {err && (
        <div role="alert" className={s.errText}>
          {err}
        </div>
      )}
    </div>
  )
}

/** ADE 채팅 안의 승인 카드 — 허용 / 이 세션에서 계속 허용 / 거부(이유) */
export function ApprovalCard({ p, via }: { p: PendingApproval; via: string }) {
  if (p.tool === 'AskUserQuestion') return <QuestionCard p={p} via={via} />
  return <PermissionCard p={p} via={via} />
}

function PermissionCard({ p, via }: { p: PendingApproval; via: string }) {
  const answer = useAnswer()
  const [reason, setReason] = useState('')
  const fileTool = ['Edit', 'Write', 'MultiEdit', 'NotebookEdit'].includes(p.tool)
  const err = answer.error instanceof ApiError ? answer.error.message : answer.error ? String(answer.error) : ''
  return (
    <div role="group" aria-label="승인 요청" className={s.approval}>
      <div className={s.approvalHead}>
        <span className={s.approvalTitle}>승인이 필요해요</span>
        <span className={s.approvalTool}>
          {p.tool} · <span className={s.mono}>{p.summary}</span>
        </span>
        <span className={s.muted}>{ago(p.createdAt)} 기다리는 중</span>
      </div>
      {p.warning && (
        <div role="alert" className={s.approvalWarn}>
          <WarningIcon />
          <span>{p.warning}</span>
        </div>
      )}
      {(p.title || p.reason) && <div className={s.approvalWhy}>{p.title || p.reason}</div>}
      <DiffView tool={p.tool} input={p.input} />
      <label htmlFor={`reason-${p.id}`} className={s.srOnly}>
        거부 이유나 다른 지시
      </label>
      <input
        id={`reason-${p.id}`}
        className={s.reason}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="거부할 때 이유나 다른 지시 (선택)"
      />
      <div className={s.approvalActions}>
        <button type="button" className={s.allow} disabled={answer.isPending} onClick={() => answer.mutate({ id: p.id, choice: 'allow', via })}>
          허용
        </button>
        <button type="button" className={s.ghostBtn} disabled={answer.isPending} onClick={() => answer.mutate({ id: p.id, choice: 'allowSession', via })}>
          {fileTool ? '이 세션에서 이 파일은 계속 허용' : '이 세션에서 같은 요청은 계속 허용'}
        </button>
        <button type="button" className={s.denyBtn} disabled={answer.isPending} onClick={() => answer.mutate({ id: p.id, choice: 'deny', reason, via })}>
          거부
        </button>
        <span className={s.muted}>같은 요청이 Dashboard, Inbox, Discord에도 표시돼요. 먼저 답한 곳의 답이 적용돼요.</span>
      </div>
      {err && (
        <div role="alert" className={s.errText}>
          {err}
        </div>
      )}
    </div>
  )
}
