import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { accountQuery } from '@/api/agents'
import { notifyQuery } from '@/api/inbox'
import { healthQuery } from '@/api/system'
import s from './StartGuide.module.css'

const KEY = 'labremote:start-guide-closed'

/**
 * 처음 실행 안내 (PLAN 7장) — Claude Code 로그인 → 프로젝트 등록 → Discord → (선택) 밖에서 접속.
 * 필수 세 단계를 마치면 저절로 사라지고, 닫으면 이 브라우저에서는 다시 안 보여요.
 */
export function StartGuide({ projects }: { projects: number }) {
  const account = useQuery(accountQuery())
  const notify = useQuery(notifyQuery())
  const health = useQuery(healthQuery())
  const [closed, setClosed] = useState(() => {
    try {
      return localStorage.getItem(KEY) === '1'
    } catch {
      return false
    }
  })
  const steps = [
    {
      done: account.data?.loggedIn === true,
      // 불러오는 중만 기다려요. 확인이 실패(null)해도 안내는 보여요
      loading: account.isPending,
      unknown: !!account.data && account.data.loggedIn === null,
      title: 'Claude Code 로그인',
      text: '데스크톱 터미널에서 claude를 열어 로그인해요. lab.remote는 그 로그인을 불러 써요.',
      to: '',
    },
    { done: projects > 0, loading: false, unknown: false, title: '프로젝트 등록', text: '연구 폴더를 등록하거나 새 폴더를 만들어요.', to: '/projects' },
    { done: !!notify.data?.webhook.set, loading: notify.isPending, unknown: notify.isError, title: 'Discord 알림', text: '답이 필요하거나 실행이 끝나면 휴대폰으로 알림을 받아요.', to: '/inbox' },
    {
      done: health.data?.tunnel === 'up',
      loading: health.isPending,
      unknown: health.isError,
      title: '밖에서 접속 (선택)',
      text: 'code tunnel로 휴대폰이나 다른 PC에서 열어요.',
      to: '/settings/system',
    },
  ]
  const required = steps.slice(0, 3)
  if (closed || required.every((x) => x.done) || required.some((x) => x.loading)) return null

  return (
    <section aria-label="시작하기" className={s.card}>
      <div className={s.head}>
        <h2 className={s.title}>시작하기</h2>
        <span className={s.muted}>
          {steps.filter((x) => x.done).length} / {steps.length}
        </span>
        <button
          type="button"
          className={s.close}
          onClick={() => {
            try {
              localStorage.setItem(KEY, '1')
            } catch {
              // 저장 못 하면 이번만 닫아요
            }
            setClosed(true)
          }}
        >
          닫기
        </button>
      </div>
      <ol className={s.steps}>
        {steps.map((x) => (
          <li key={x.title} className={s.step} data-done={x.done}>
            <span aria-hidden="true" className={s.mark}>
              {x.done ? '✓' : ''}
            </span>
            <span className={s.body}>
              <span className={s.stepTitle}>{x.to && !x.done ? <Link to={x.to}>{x.title}</Link> : x.title}</span>
              {!x.done && <span className={s.muted}>{x.unknown ? `확인하지 못했어요 · ${x.text}` : x.text}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}
