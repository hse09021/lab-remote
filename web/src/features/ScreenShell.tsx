import { useSearchParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import s from './ScreenShell.module.css'

export interface ShellSection {
  title: string
  /** 어느 단계에서 채워지나 (PLAN 6장) */
  step: number
  note?: string
}

interface Props {
  title: string
  /** 목업 파일 이름 (docs/v3/mockups/) */
  mockup: string
  /** 보기 전환 — `?view=` 로 주소에 남아요 */
  views?: { id: string; label: string; sections: ShellSection[] }[]
  sections?: ShellSection[]
  /** 제목 옆 버튼 자리 */
  actions?: ReactNode
  /** 왼쪽 목록 자리 (Dashboard 의 에이전트 목록 등) */
  aside?: ShellSection
}

/**
 * 1단계의 화면 껍데기. 라우트 · 제목 · 보기 전환 · 구역 자리만 있고,
 * 구역마다 어느 단계에서 채워지는지 적어 둬요. 해당 단계에서 목업대로 다시 만들어요.
 */
export function ScreenShell({ title, mockup, views, sections, actions, aside }: Props) {
  const [params, setParams] = useSearchParams()
  const current = views?.find((v) => v.id === params.get('view')) ?? views?.[0]
  const shown = current?.sections ?? sections ?? []

  return (
    <div className={s.page}>
      {aside && (
        <aside aria-label={aside.title} className={s.aside}>
          <div className={s.asideTitle}>{aside.title}</div>
          <Placeholder section={aside} />
        </aside>
      )}
      <main className={s.main}>
        <div className={s.head}>
          <h1 className={s.title}>{title}</h1>
          {views && (
            <div role="tablist" aria-label={`${title} 보기`} className={s.views}>
              {views.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  role="tab"
                  aria-selected={v.id === current?.id}
                  className={s.view}
                  onClick={() => {
                    const next = new URLSearchParams(params)
                    next.set('view', v.id)
                    setParams(next, { replace: true })
                  }}
                >
                  {v.label}
                </button>
              ))}
            </div>
          )}
          {actions && <div className={s.actions}>{actions}</div>}
        </div>
        <div className={s.grid}>
          {shown.map((sec) => (
            <section key={sec.title} aria-label={sec.title} className={s.card}>
              <h2 className={s.cardTitle}>{sec.title}</h2>
              <Placeholder section={sec} />
            </section>
          ))}
        </div>
        <p className={s.source}>docs/v3/mockups/{mockup}</p>
      </main>
    </div>
  )
}

function Placeholder({ section }: { section: ShellSection }) {
  return (
    <div className={s.placeholder}>
      <span className={s.step}>{section.step}단계에서 붙어요</span>
      {section.note && <span className={s.note}>{section.note}</span>}
    </div>
  )
}
