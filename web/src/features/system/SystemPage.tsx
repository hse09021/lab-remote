import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { sessionsQuery } from '@/api/agents'
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
  if (t.state === 'absent') return { label: 'code tunnel', value: '없음', sub: ['VS Code CLI를 찾지 못했어요', '원격 접속할 때만 필요해요'], tone: 'off' }
  if (t.state === 'unknown') return { label: 'code tunnel', value: '알 수 없음', sub: [t.detail || '상태를 확인하지 못했어요'], tone: 'warn' }
  if (t.state === 'off')
    return {
      label: 'code tunnel',
      value: '중지됨',
      sub: [t.loggedIn === false ? '로그인 안 됨' : t.loggedIn ? '로그인됨' : '로그인 상태 알 수 없음', t.service ? '서비스는 설치됨' : '서비스 없음'],
      tone: 'off',
    }
  return {
    label: 'code tunnel',
    value: '연결됨',
    sub: [t.url ? t.url.replace(/^https:\/\//, '') : '주소를 확인하지 못했어요', t.service ? '서비스로 실행 중이에요' : '직접 실행 · 재부팅하면 종료돼요'],
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
      sub: [`127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}`, `가동 시간 ${duration(d.server.uptimeSec)} · pid ${d.server.pid}`],
      tone: 'ok',
    },
    tunnelCard(d),
    {
      label: '자동 시작',
      value: !a.installed ? '비활성' : on ? '활성' : a.active || '설치만 됨',
      sub: [
        a.installed ? `labremote-session${a.restarts ? ` · 재시작 ${a.restarts}회` : ''}` : '사용자 서비스 없음',
        `linger ${a.linger === null ? '알 수 없음' : a.linger ? 'yes' : 'no'}`,
      ],
      tone: on && a.linger ? 'ok' : a.installed ? 'warn' : 'off',
    },
    {
      label: 'GPU',
      value: g.available ? (dev?.name ?? 'GPU') : '조회 불가',
      sub: g.available
        ? [`드라이버 ${g.driver.userland ?? dev?.driver ?? '?'}`, g.driver.mismatch ? '커널 · 유저랜드 버전 불일치 (재부팅 필요)' : '커널 · 유저랜드 버전 일치']
        : [g.reason || 'nvidia-smi 결과를 읽지 못했어요'],
      tone: !g.available || g.driver.mismatch ? 'warn' : 'ok',
    },
  ]
}

function tree(d: SystemOverview, live: { live: number; open: number } | null) {
  const a = d.autostart
  const t = d.tunnel
  const clock = d.clock
  const next = clock?.next
    ? `다음 ${new Date(clock.next.at * 1000).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} · ${clock.next.name}`
    : '예약 없음'
  const head = a.installed
    ? `부팅 → labremote-session.service   ${a.active === 'active' ? '●' : '○'} ${a.active || '?'}${a.restarts ? ` (재시작 ${a.restarts}회)` : ''}`
    : '부팅 → (자동 시작 비활성 · 지금은 직접 실행한 서버)'
  const tunnelLine = t.state === 'up' ? `● 연결됨${t.service ? ' · VS Code 서비스' : ' · 직접 실행'}` : t.state === 'off' ? '○ 중지됨' : t.state === 'absent' ? '○ 없음' : '? 알 수 없음'
  return `${head}
  └ tmux "labremote"
      └ labremote serve    ● 127.0.0.1:${d.server.port ?? '?'} · nice ${d.server.nice ?? '?'}
          ├ 예약 스케줄러  ${clock?.running ? '●' : '○'} ${next}${clock?.waiting.length ? ` · GPU 대기 중 ${clock.waiting.length}` : ''}
          └ 에이전트 세션  Agent SDK · ${live ? `연결 ${live.live} / 4 · 열린 세션 ${live.open}` : '동시 4개까지'}
code tunnel (VS Code가 따로 실행해요)   ${tunnelLine}`
}

export default function SystemPage() {
  const sys = useQuery(systemQuery())
  // 지금 연결된 에이전트 세션 수 (자동 시작 구조 그림에)
  const agents = useQuery(sessionsQuery())
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
        <p className={s.text}>lab.remote가 이 데스크톱에서 어떻게 실행되고 있는지, 무엇을 변경했는지 보여 줘요. 여기에 없는 시스템 설정은 변경하지 않아요.</p>
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
          lab.remote가 변경한 항목
        </h2>
        <p className={s.text}>
          이 목록이 전부예요. 그 밖의 데이터는 lab.remote 데이터 폴더(<span className={s.mono}>{d.server.dataDir}</span>)와, 등록한 프로젝트마다 하나씩
          있는 <span className={s.mono}>.labremote/</span>에만 저장돼요.
        </p>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>항목</th>
                <th>위치</th>
                <th>생성 시각</th>
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
          <pre className={s.pre}>{tree(d, agents.data ? { live: agents.data.live, open: agents.data.sessions.length } : null)}</pre>
          {a.installed ? (
            <p className={s.text}>
              재부팅하면 로그인하지 않아도 바로 실행돼요. 학습은 이 서비스와 분리돼 있어서 세션을 다시 시작해도 계속 실행돼요. 예약 실행은 이 서버가 시각을 확인하므로
              서버가 중지되어 있으면 실행되지 않아요. 서버 출력은 <span className={s.mono}>{a.tmux}</span> 명령으로 확인할 수 있어요.
              {!a.inside && ' 지금 보고 있는 서버는 자동 시작과 별개로 직접 실행한 서버예요.'}
            </p>
          ) : (
            <p className={s.text}>
              자동 시작이 비활성화되어 있어요. 활성화하려면 데스크톱 터미널에서 <span className={s.mono}>{a.installCommand}</span> 명령을 실행해 주세요. 변경될 내용을 먼저 보여 주고 확인을 받아요.
              {a.systemctl ? '' : ' (systemctl이 없어 이 컴퓨터에서는 사용할 수 없어요)'}
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
                {restart.isSuccess ? '다시 시작하는 중…' : '세션 다시 시작'}
              </button>
              <button type="button" className={s.dangerBtn} onClick={() => setAsking(true)}>
                자동 시작 끄기…
              </button>
            </div>
          )}
          {restart.isSuccess && a.inside && <p className={s.note}>이 서버도 다시 시작돼요. 잠시 연결이 끊겼다가 자동으로 다시 연결돼요.</p>}
          {restart.isError && <p className={s.err}>{errText(restart.error)}</p>}
        </section>

        <section className={s.section} aria-labelledby="sys-notify">
          <h2 id="sys-notify" className={s.h2}>
            알림
          </h2>
          <div className={s.rows}>
            <div className={s.row}>
              <span>Discord 웹훅</span>
              <span>{notify.data ? (notify.data.webhook.set ? `설정됨 · ${notify.data.webhook.masked}` : '설정 안 됨') : '…'}</span>
            </div>
            <div className={s.row}>
              <span>보낼 알림</span>
              <span>
                {rules.length}개 중 {rules.filter((r) => r.on).length}개 활성화 · <Link to="/inbox">Inbox에서 변경</Link>
              </span>
            </div>
            <div className={s.row}>
              <span>승인 요청</span>
              <span>{d.tunnel.publicUrl ? 'Inbox · Discord (답하기 링크 포함)' : 'Inbox · Discord (외부 주소를 입력하면 답하기 링크가 포함돼요)'}</span>
            </div>
          </div>
          <div className={s.actions}>
            <button type="button" className={s.btn} disabled={!notify.data?.webhook.set || test.isPending} onClick={() => test.mutate()}>
              테스트 알림 보내기
            </button>
            {test.isSuccess && <span className={s.note}>{test.data.sent ? '보냈어요' : (test.data.detail ?? '보내지 못했어요')}</span>}
          </div>
        </section>
      </div>

      <RemoteSection d={d} />

      <section className={s.section} aria-labelledby="sys-sec">
        <h2 id="sys-sec" className={s.h2}>
          보안
        </h2>
        <p className={s.text}>
          터널이 실행 중이면 해당 GitHub 계정만으로 이 데스크톱의 터미널과 파일에 접근할 수 있어요. GitHub 2단계 인증을 꼭 활성화해 주세요. 서버는
          127.0.0.1에서만 요청을 받으므로 터널을 거치지 않으면 접속할 수 없고, 등록한 외부 주소가 아닌 곳에서 온 요청은 거부해요.
        </p>
      </section>

      <section className={s.section} aria-labelledby="sys-rm">
        <h2 id="sys-rm" className={s.h2}>
          삭제
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
          labremote-session 서비스를 중지하고 유닛 파일을 삭제해요.{' '}
          {a.lingerBefore === false
            ? d.tunnel.service
              ? 'linger는 code tunnel 서비스도 사용하고 있어서 그대로 유지해요.'
              : 'linger는 원래 값(no)으로 되돌려요.'
            : 'linger는 lab.remote가 활성화한 것이 아니어서 그대로 유지해요.'}
        </span>
        <span>학습은 별도로 실행되므로 중지되지 않아요. {a.inside && '지금 보고 있는 이 서버도 종료되어 화면 연결이 끊겨요.'} 다시 활성화하려면 터미널에서 labremote autostart install을 실행해 주세요.</span>
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
        원격 접속
      </h2>
      <p className={s.text}>
        터널은 VS Code가 실행하고, lab.remote는 상태만 확인해요. 처음 한 번만 설정하면 돼요{t.state === 'up' ? ' (터널은 이미 실행 중이에요)' : ''}.
      </p>
      <pre className={s.pre}>{`code tunnel user login --provider github
code tunnel service install --accept-server-license-terms
# 휴대폰이나 다른 PC에서 ${t.url || 'https://vscode.dev/tunnel/<이름>'} 주소를 열고
# Ports 보기에서 ${d.server.port ?? 8000} 포트를 전달(Forward a Port) → Forwarded Address를 아래에 입력해요`}</pre>
      <form
        className={s.remoteForm}
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate(url.trim())
        }}
      >
        <label htmlFor="sys-remote-url" className={s.label}>
          외부 주소
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
        입력하면 이 주소로 오는 요청을 허용하고, Discord 알림에 &lsquo;답하기&rsquo; 링크가 포함돼요.
        {via && ` 지금 보고 있는 주소: ${window.location.hostname}`}
        {d.tunnel.envHosts.length > 0 && ` 환경 변수로 허용한 주소: ${d.tunnel.envHosts.join(', ')}`}
      </p>
      {save.isError && <p className={s.err}>{errText(save.error)}</p>}
    </section>
  )
}
