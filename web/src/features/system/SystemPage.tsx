import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { systemQuery } from '@/api/system'
import type { SystemOverview } from '@/api/system'
import { ErrorState, LoadingState } from '@/components'
import { duration } from '@/lib/time'
import s from './System.module.css'

type Tone = 'ok' | 'warn' | 'off'

interface Card {
  label: string
  value: string
  sub: string[]
  tone: Tone
}

function cards(d: SystemOverview): Card[] {
  const a = d.autostart
  const g = d.gpu
  const dev = g.devices[0]
  const on = a.enabled === 'enabled' && a.active === 'active'
  return [
    {
      label: 'lab.remote 서버',
      value: '실행 중',
      sub: [
        `127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}`,
        `켜진 지 ${duration(d.server.uptimeSec)} · pid ${d.server.pid}`,
      ],
      tone: 'ok',
    },
    {
      label: 'code tunnel',
      value: '모름',
      sub: [d.tunnel.note ?? '[확인 필요]'],
      tone: 'off',
    },
    {
      label: '자동 시작',
      value: !a.installed ? '꺼짐' : on ? '켜짐' : '설치만 됨',
      sub: [
        a.installed ? `labremote-session · ${a.enabled || '?'} · ${a.active || '?'}` : '사용자 서비스 없음',
        `linger ${a.linger === null ? '모름' : a.linger ? 'yes' : 'no'}`,
      ],
      tone: on && a.linger ? 'ok' : a.installed ? 'warn' : 'off',
    },
    {
      label: 'GPU',
      value: g.available ? (dev?.name ?? 'GPU') : '조회 불가',
      sub: g.available
        ? [
            `드라이버 ${g.driver.userland ?? dev?.driver ?? '?'}`,
            g.driver.mismatch ? '커널·유저랜드 다름 — 재부팅 필요' : '커널·유저랜드 같음',
          ]
        : [g.reason || 'nvidia-smi 를 못 읽었어요'],
      tone: !g.available || g.driver.mismatch ? 'warn' : 'ok',
    },
  ]
}

export default function SystemPage() {
  const sys = useQuery(systemQuery())

  if (sys.isPending) return <LoadingState label="시스템 상태를 불러오는 중이에요" />
  if (sys.isError) return <ErrorState error={sys.error} onRetry={() => sys.refetch()} />
  const d = sys.data

  return (
    <main className={s.page}>
      <h1 className={s.title}>시스템</h1>

      <div className={s.cards}>
        {cards(d).map((c) => (
          <div key={c.label} className={s.card}>
            <div className={s.cardLabel}>
              <span aria-hidden="true" className={s.dot} data-tone={c.tone} />
              {c.label}
            </div>
            <div className={s.cardValue}>{c.value}</div>
            {c.sub.map((line) => (
              <div key={line} className={s.cardSub}>
                {line}
              </div>
            ))}
          </div>
        ))}
      </div>

      <section className={s.section} aria-labelledby="sys-changes">
        <h2 id="sys-changes" className={s.h2}>
          lab.remote 가 바꾼 것
        </h2>
        <p className={s.text}>
          이게 전부예요. 나머지 상태는 lab.remote 데이터 폴더(<span className={s.mono}>{d.server.dataDir}</span>)와,
          등록한 프로젝트마다 하나씩 있는 <span className={s.mono}>.labremote/</span> 에만 있어요.
        </p>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>무엇</th>
                <th>어디</th>
                <th>언제 생겼나</th>
                <th>되돌리기</th>
              </tr>
            </thead>
            <tbody>
              {d.changes.map((c) => (
                <tr key={c.what} data-present={c.present === false ? 'no' : 'yes'}>
                  <td>
                    {c.what}
                    {c.present === false && <span className={s.absent}>없음</span>}
                  </td>
                  <td className={s.mono}>{c.where || '—'}</td>
                  <td>{c.when}</td>
                  <td className={s.mono}>{c.project ? <Link to={`/projects/${encodeURIComponent(c.project)}?tab=settings`}>{c.undo}</Link> : c.undo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={s.two}>
        <section className={s.section} aria-labelledby="sys-auto">
          <h2 id="sys-auto" className={s.h2}>
            자동 시작
          </h2>
          <pre className={s.pre}>
            {`부팅 → labremote-session.service   ${d.autostart.installed ? '● 있음' : '○ 없음'}
  └ labremote serve    ● 127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}
      ├ code tunnel      [확인 필요] 9단계
      ├ 예약 시계        ${d.clock?.running ? '●' : '○'} ${d.clock?.next ? `다음 ${new Date(d.clock.next.at * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} · ${d.clock.next.name}` : '예약 없음'}${d.clock?.waiting.length ? ` · GPU 기다리는 중 ${d.clock.waiting.length}` : ''}
      └ 에이전트 세션    Agent SDK · 동시 4개까지`}
          </pre>
          <p className={s.text}>
            켜고 끄기는 9단계에서 <span className={s.mono}>labremote autostart</span> 로 붙어요. 학습은 이 서버와 분리돼서
            서버를 다시 켜도 살아요(2단계).
          </p>
        </section>

        <section className={s.section} aria-labelledby="sys-notify">
          <h2 id="sys-notify" className={s.h2}>
            알림
          </h2>
          <p className={s.text}>
            Discord 웹훅 · 보낼 알림 · 조용한 시간은 <Link to="/inbox">Inbox</Link> 에서 바꿔요. 웹훅 주소는 데이터 폴더에
            권한 600 으로만 두고 화면에는 가려서 보여요.
          </p>
        </section>
      </div>

      <section className={s.section} aria-labelledby="sys-sec">
        <h2 id="sys-sec" className={s.h2}>
          보안
        </h2>
        <p className={s.text}>
          서버는 127.0.0.1 에만 열려서 터널을 거치지 않으면 닿지 않아요. 다른 사이트에서 이 서버로 보낸 요청은 거절해요(주소 ·
          출처 검사). 터널을 열면 그 계정만 있으면 이 데스크톱의 터미널과 파일에 들어올 수 있으니, 터널 계정에 2단계 인증을
          켜 두세요.
        </p>
      </section>

      <section className={s.section} aria-labelledby="sys-rm">
        <h2 id="sys-rm" className={s.h2}>
          지우기
        </h2>
        <pre className={s.pre}>
          {`systemctl --user disable --now labremote-session   # 자동 시작을 켰다면
conda env remove -n labremote
rm -rf <lab.remote 를 받은 폴더>
# 등록했던 프로젝트의 .labremote/ 는 남아요. 필요하면 프로젝트마다 지워요.`}
        </pre>
      </section>
    </main>
  )
}
