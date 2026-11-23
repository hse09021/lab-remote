import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { sessionsQuery } from '@/api/agents'
import { papersQuery } from '@/api/papers'
import { projectsQuery } from '@/api/projects'
import s from './GotoPalette.module.css'

interface Item {
  group: string
  label: string
  sub: string
  to: string
  /** 찾을 때 함께 보는 글 */
  hay: string
}

const SCREENS: Item[] = [
  { group: '화면', label: 'Dashboard', sub: '오늘 · 답 필요 · 실행', to: '/dashboard', hay: 'dashboard 대시보드' },
  { group: '화면', label: 'Dashboard › Agents', sub: '에이전트 그래프', to: '/dashboard?view=agents', hay: 'agents 에이전트' },
  { group: '화면', label: 'Dashboard › Schedule', sub: '예약', to: '/dashboard?view=schedule', hay: 'schedule 예약' },
  { group: '화면', label: 'Projects', sub: '프로젝트 목록', to: '/projects', hay: 'projects 프로젝트' },
  { group: '화면', label: 'Papers', sub: '라이브러리', to: '/papers', hay: 'papers 논문 라이브러리' },
  { group: '화면', label: 'Papers › Graph', sub: '지식그래프', to: '/papers?view=graph', hay: 'graph 그래프' },
  { group: '화면', label: 'Inbox', sub: '알림', to: '/inbox', hay: 'inbox 알림' },
  { group: '화면', label: 'Conda', sub: '환경 관리', to: '/settings/conda', hay: 'conda 환경' },
  { group: '화면', label: 'System', sub: '서버 · 터널 · 자동 시작', to: '/settings/system', hay: 'system 시스템 터널' },
]

/**
 * Go to… (Ctrl/⌘+K) — 화면 · 프로젝트 · 논문 · 에이전트 세션으로 바로 가요.
 * 목업은 버튼만 있어서 창 모양은 lab.remote 공통 창(Dialog)에 맞췄어요.
 */
export function GotoPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [pick, setPick] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  // 열었을 때만 불러와요
  const projects = useQuery({ ...projectsQuery(), enabled: open })
  const papers = useQuery({ ...papersQuery(), enabled: open })
  const sessions = useQuery({ ...sessionsQuery(), enabled: open })

  useEffect(() => {
    if (open) {
      setQ('')
      setPick(0)
      setTimeout(() => input.current?.focus(), 0)
    }
  }, [open])

  const items = useMemo<Item[]>(() => {
    const out = [...SCREENS]
    for (const p of projects.data?.projects ?? []) {
      const base = `/projects/${encodeURIComponent(p.name)}`
      out.push({ group: '프로젝트', label: p.name, sub: p.path, to: base, hay: `${p.name} ${p.path}` })
      out.push({ group: '프로젝트', label: `${p.name} › IDE`, sub: '편집기 · 터미널', to: `${base}/ide`, hay: `${p.name} ide` })
      out.push({ group: '프로젝트', label: `${p.name} › ADE`, sub: '에이전트 세션', to: `${base}/ade`, hay: `${p.name} ade` })
    }
    for (const p of papers.data ?? []) {
      out.push({ group: '논문', label: p.title, sub: p.authors, to: `/papers/${encodeURIComponent(p.id)}`, hay: `${p.title} ${p.authors} ${p.id}` })
    }
    for (const x of sessions.data?.sessions ?? []) {
      out.push({
        group: '세션',
        label: x.title || '(제목 없음)',
        sub: `${x.project} · ${x.stateLabel}`,
        to: `/projects/${encodeURIComponent(x.project)}/ade?session=${encodeURIComponent(x.id)}`,
        hay: `${x.title} ${x.project} ${x.branch}`,
      })
    }
    return out
  }, [projects.data, papers.data, sessions.data])

  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const shown = (words.length ? items.filter((it) => words.every((w) => `${it.label} ${it.hay}`.toLowerCase().includes(w))) : items).slice(0, 50)

  useEffect(() => {
    setPick(0)
  }, [q])
  useEffect(() => {
    listRef.current?.querySelector('[data-picked="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [pick])

  if (!open) return null
  const go = (it: Item | undefined) => {
    if (!it) return
    onClose()
    navigate(it.to)
  }

  return (
    <div className={s.backdrop} onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label="Go to" className={s.box}>
        <input
          ref={input}
          className={s.input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="화면 · 프로젝트 · 논문 · 세션 찾기"
          aria-label="찾기"
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose()
            else if (e.key === 'ArrowDown') {
              e.preventDefault()
              setPick((n) => Math.min(n + 1, shown.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setPick((n) => Math.max(n - 1, 0))
            } else if (e.key === 'Enter' && !e.nativeEvent.isComposing) go(shown[pick])
          }}
        />
        <ul ref={listRef} className={s.list} role="listbox" aria-label="찾은 곳">
          {shown.map((it, i) => (
            <li key={`${it.group}${it.to}${it.label}`}>
              {(i === 0 || shown[i - 1].group !== it.group) && <div className={s.group}>{it.group}</div>}
              <button
                type="button"
                role="option"
                aria-selected={i === pick}
                data-picked={i === pick}
                className={s.item}
                onMouseEnter={() => setPick(i)}
                onClick={() => go(it)}
              >
                <span className={s.label}>{it.label}</span>
                <span className={s.sub}>{it.sub}</span>
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className={s.empty}>찾는 게 없어요.</li>}
        </ul>
        <div className={s.foot}>↑↓ 고르기 · Enter 가기 · Esc 닫기</div>
      </div>
    </div>
  )
}
