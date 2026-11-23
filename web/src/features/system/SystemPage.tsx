import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { notifyQuery, useTestSend } from '@/api/inbox'
import { systemQuery, useRestartSession, useSetRemote, useUninstallAutostart } from '@/api/system'
import type { SystemOverview } from '@/api/system'
import { Dialog, ErrorState, LoadingState } from '@/components'
import { duration } from '@/lib/time'
import s from './System.module.css'

type Tone = 'ok' | 'warn' | 'off'

interface Card {
  label: string
  value: string
  sub: string[]
  tone: Tone
}

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : '')

function tunnelCard(d: SystemOverview): Card {
  const t = d.tunnel
  if (t.state === 'absent') return { label: 'code tunnel', value: '없음', sub: ['VS Code CLI 를 못 찾았어요', '밖에서 쓸 때만 필요해요'], tone: 'off' }
  if (t.state === 'unknown') return { label: 'code tunnel', value: '모름', sub: [t.detail || '상태를 못 읽었어요'], tone: 'warn' }
  if (t.state === 'off')
    return {
      label: 'code tunnel',
      value: '꺼짐',
      sub: [t.loggedIn === false ? '로그인 안 함' : t.loggedIn ? '로그인함' : '로그인 모름', t.service ? '서비스는 설치됨' : '서비스 없음'],
      tone: 'off',
    }
  return {
    label: 'code tunnel',
    value: '연결됨',
    sub: [t.url ? t.url.replace(/^https:\/\//, '') : '이름은 못 읽었어요', t.service ? '서비스로 켜져 있어요' : '손으로 띄움 · 재부팅하면 꺼져요'],
    tone: t.service ? 'ok' : 'warn',
  }
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
      sub: [`127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}`, `켜진 지 ${duration(d.server.uptimeSec)} · pid ${d.server.pid}`],
      tone: 'ok',
    },
    tunnelCard(d),
    {
      label: '자동 시작',
      value: !a.installed ? '꺼짐' : on ? '켜짐' : a.active || '설치만 됨',
      sub: [
        a.installed ? `labremote-session${a.restarts ? ` · 재시작 ${a.restarts}회` : ''}` : '사용자 서비스 없음',
        `linger ${a.linger === null ? '모름' : a.linger ? 'yes' : 'no'}`,
      ],
      tone: on && a.linger ? 'ok' : a.installed ? 'warn' : 'off',
    },
    {
      label: 'GPU',
      value: g.available ? (dev?.name ?? 'GPU') : '조회 불가',
      sub: g.available
        ? [`드라이버 ${g.driver.userland ?? dev?.driver ?? '?'}`, g.driver.mismatch ? '커널·유저랜드 다름 — 재부팅 필요' : '커널·유저랜드 같음']
        : [g.reason || 'nvidia-smi 를 못 읽었어요'],
      tone: !g.available || g.driver.mismatch ? 'warn' : 'ok',
    },
  ]
}

function tree(d: SystemOverview) {
  const a = d.autostart
  const t = d.tunnel
  const clock = d.clock
  const next = clock?.next
    ? `다음 ${new Date(clock.next.at * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} · ${clock.next.name}`
    : '예약 없음'
  const head = a.installed
    ? `부팅 → labremote-session.service   ${a.active === 'active' ? '●' : '○'} ${a.active || '?'}${a.restarts ? ` (재시작 ${a.restarts}회)` : ''}`
    : '부팅 → (자동 시작 꺼짐 — 지금은 손으로 띄운 서버)'
  const tunnelLine = t.state === 'up' ? `● 연결됨${t.service ? ' · VS Code 서비스' : ' · 손으로 띄움'}` : t.state === 'off' ? '○ 꺼짐' : t.state === 'absent' ? '○ 없음' : '? 모름'
  return `${head}
  └ tmux "labremote"
      └ labremote serve    ● 127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}
          ├ 예약 시계      ${clock?.running ? '●' : '○'} ${next}${clock?.waiting.length ? ` · GPU 기다리는 중 ${clock.waiting.length}` : ''}
          └ 에이전트 세션  Agent SDK · 동시 4개까지
code tunnel (VS Code 가 따로 띄워요)   ${tunnelLine}`
}

export default function SystemPage() {
  const sys = useQuery(systemQuery())
  const notify = useQuery(notifyQuery())
  const restart = useRestartSession()
  const uninstall = useUninstallAutostart()
  const test = useTestSend()
  const [asking, setAsking] = useState(false)

  if (sys.isPending) return <LoadingState label="시스템 상태를 불러오는 중이에요" />
  if (sys.isError) return <ErrorState error={sys.error} onRetry={() => sys.refetch()} />
  const d = sys.data
  const a = d.autostart
  const rules = notify.data?.rules ?? []

  return (
    <main className={s.page}>
      <div>
        <h1 className={s.title}>시스템</h1>
        <p className={s.text}>lab.remote 가 이 데스크톱에서 어떻게 떠 있는지, 무엇을 바꿨는지 보여 줘요. 여기 없는 시스템 설정은 건드리지 않아요.</p>
      </div>

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
          이게 전부예요. 나머지 상태는 lab.remote 데이터 폴더(<span className={s.mono}>{d.server.dataDir}</span>)와, 등록한 프로젝트마다 하나씩
          있는 <span className={s.mono}>.labremote/</span> 에만 있어요.
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
                  <td className={s.mono}>
                    {c.project ? <Link to={`/projects/${encodeURIComponent(c.project)}?tab=settings`}>{c.undo}</Link> : c.undo}
                  </td>
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
          <pre className={s.pre}>{tree(d)}</pre>
          {a.installed ? (
            <p className={s.text}>
              재부팅해도 로그인 없이 바로 떠요. 학습은 이 서비스와 분리돼서 세션을 다시 켜도 살아요. 예약은 이 서버가 시간을 재서, 서버가 꺼져
              있으면 돌지 않아요. 서버 출력은 <span className={s.mono}>{a.tmux}</span> 로 봐요.
              {!a.inside && ' 지금 보고 있는 서버는 자동 시작 밖에서 띄운 것이에요.'}
            </p>
          ) : (
            <p className={s.text}>
              꺼져 있어요. 켜려면 데스크톱 터미널에서 <span className={s.mono}>{a.installCommand}</span> — 무엇이 바뀌는지 먼저 보여 주고 물어봐요.
              {a.systemctl ? '' : ' (systemctl 이 없어 이 컴퓨터에서는 쓸 수 없어요)'}
            </p>
          )}
          {a.installed && (
            <div className={s.actions}>
              <button
                type="button"
                className={s.btn}
                disabled={restart.isPending || restart.isSuccess}
                onClick={() => restart.mutate()}
              >
                {restart.isSuccess ? '다시 켜는 중…' : '세션 다시 켜기'}
              </button>
              <button type="button" className={s.dangerBtn} onClick={() => setAsking(true)}>
                자동 시작 끄기…
              </button>
            </div>
          )}
          {restart.isSuccess && a.inside && <p className={s.note}>이 서버도 다시 떠요. 잠깐 끊겼다가 저절로 돌아와요.</p>}
          {restart.isError && <p className={s.err}>{errText(restart.error)}</p>}
        </section>

        <section className={s.section} aria-labelledby="sys-notify">
          <h2 id="sys-notify" className={s.h2}>
            알림
          </h2>
          <div className={s.rows}>
            <div className={s.row}>
              <span>Discord 웹훅</span>
              <span>{notify.data ? (notify.data.webhook.set ? `설정됨 · ${notify.data.webhook.masked}` : '없음') : '…'}</span>
            </div>
            <div className={s.row}>
              <span>보내는 것</span>
              <span>
                {rules.length}가지 중 {rules.filter((r) => r.on).length}개 · <Link to="/inbox">Inbox 에서 바꾸기</Link>
              </span>
            </div>
            <div className={s.row}>
              <span>승인 요청</span>
              <span>{d.tunnel.publicUrl ? 'Inbox · Discord (답하기 링크 붙음)' : 'Inbox · Discord (바깥 주소를 적으면 답하기 링크가 붙어요)'}</span>
            </div>
          </div>
          <div className={s.actions}>
            <button type="button" className={s.btn} disabled={!notify.data?.webhook.set || test.isPending} onClick={() => test.mutate()}>
              시험 알림 보내기
            </button>
            {test.isSuccess && <span className={s.note}>{test.data.sent ? '보냈어요' : (test.data.detail ?? '못 보냈어요')}</span>}
          </div>
        </section>
      </div>

      <RemoteSection d={d} />

      <section className={s.section} aria-labelledby="sys-sec">
        <h2 id="sys-sec" className={s.h2}>
          보안
        </h2>
        <p className={s.text}>
          터널이 늘 열려 있으면 그 GitHub 계정만 있으면 이 데스크톱의 터미널과 파일에 들어올 수 있어요. GitHub 2단계 인증을 켜 두세요. 서버는
          127.0.0.1 에만 열려서 터널을 거치지 않으면 닿지 않고, 적어 둔 바깥 주소가 아닌 곳에서 온 요청은 거절해요.
        </p>
      </section>

      <section className={s.section} aria-labelledby="sys-rm">
        <h2 id="sys-rm" className={s.h2}>
          지우기
        </h2>
        <pre className={s.pre}>{d.uninstall.join('\n')}</pre>
      </section>

      <Dialog
        open={asking}
        title="자동 시작 끄기"
        confirmLabel="끄기"
        tone="danger"
        busy={uninstall.isPending}
        error={errText(uninstall.error) || undefined}
        onClose={() => {
          uninstall.reset()
          setAsking(false)
        }}
        onConfirm={() => uninstall.mutate(undefined, { onSuccess: () => setAsking(false) })}
      >
        <span>
          labremote-session 서비스를 멈추고 유닛 파일을 지워요.{' '}
          {a.lingerBefore === false ? 'linger 는 원래대로(no) 돌려요.' : 'linger 는 lab.remote 가 켠 게 아니라 그대로 둬요.'}
        </span>
        <span>학습 실행은 따로 돌아서 계속 돌아요. {a.inside && '지금 보고 있는 이 서버도 꺼져서 화면이 끊겨요.'} 다시 켜려면 터미널에서 labremote autostart install.</span>
      </Dialog>
    </main>
  )
}

function RemoteSection({ d }: { d: SystemOverview }) {
  const save = useSetRemote()
  const [url, setUrl] = useState(d.tunnel.publicUrl)
  const t = d.tunnel
  const via = typeof window !== 'undefined' && !['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname)

  return (
    <section className={s.section} aria-labelledby="sys-remote">
      <h2 id="sys-remote" className={s.h2}>
        밖에서 접속
      </h2>
      <p className={s.text}>
        터널은 VS Code 가 띄워요 — lab.remote 는 상태만 읽어요. 한 번만 하면 돼요{t.state === 'up' ? ' (터널은 이미 켜져 있어요)' : ''}.
      </p>
      <pre className={s.pre}>{`code tunnel user login --provider github
code tunnel service install --accept-server-license-terms
# 휴대폰 · 다른 PC 에서 ${t.url || 'https://vscode.dev/tunnel/<이름>'} 를 열고
# Ports 보기에서 ${d.server.port ?? 8000} 을 전달(Forward a Port) → Forwarded Address 를 아래에 적어요`}</pre>
      <form
        className={s.remoteForm}
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate(url.trim())
        }}
      >
        <label htmlFor="sys-remote-url" className={s.label}>
          바깥 주소
        </label>
        <input
          id="sys-remote-url"
          className={s.input}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…  (Ports 보기의 Forwarded Address)"
        />
        <button type="submit" className={s.btn} disabled={save.isPending || url.trim() === d.tunnel.publicUrl}>
          {url.trim() ? '저장' : '지우기'}
        </button>
      </form>
      <p className={s.note}>
        적으면 이 주소로 오는 요청을 받고, Discord 알림에 &lsquo;답하기&rsquo; 링크가 붙어요.
        {via && ` 지금 ${window.location.hostname} 으로 보고 있어요.`}
        {d.tunnel.envHosts.length > 0 && ` 환경 변수로 허용한 주소: ${d.tunnel.envHosts.join(', ')}`}
      </p>
      {save.isError && <p className={s.err}>{errText(save.error)}</p>}
    </section>
  )
}
