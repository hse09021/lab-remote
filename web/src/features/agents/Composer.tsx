import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { agentInfoQuery } from '@/api/agents'
import type { AgentModel, ModeId } from '@/api/agents'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './Agents.module.css'

/* ChatPanel 입력창 — VS Code Claude Code 확장과 같은 구성 (목업 IDE · ADE).
 * 모델 목록과 Effort 단계는 에이전트에서 받아요(하드코딩하지 않아요). */

export const MODE_INFO: Record<ModeId, { name: string; desc: string; icon: string }> = {
  manual: { name: 'Manual', desc: '파일을 고치기 전에 매번 승인을 받아요.', icon: '✋' },
  edit: { name: 'Edit automatically', desc: '파일 수정은 바로 하고, 명령 실행은 물어봐요.', icon: '</>' },
  plan: { name: 'Plan', desc: '코드를 살펴보고 계획을 먼저 보여 준 뒤 고쳐요.', icon: '☰' },
  auto: { name: 'Auto', desc: '안전 검사를 통과한 작업은 승인하고, 위험해 보이면 멈추고 물어봐요.', icon: 'ϟ' },
}
const EFFORT_NAMES: Record<string, string> = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max' }

export interface ComposerSettings {
  mode: ModeId
  model: string
  effort: string
  ultracode?: boolean
}

interface Props {
  settings: ComposerSettings
  onSettings: (next: Partial<ComposerSettings>) => void
  onSend: (text: string) => void
  busy?: boolean
  disabled?: boolean
  placeholder?: string
}

function chipName(m: AgentModel | undefined) {
  if (!m) return 'Default'
  // "Default (recommended)" 는 실제로 쓰이는 모델 이름으로 보여요
  if (m.value === 'default' && m.description) return m.description.split('·')[0].trim() || m.displayName
  return m.displayName
}

export function Composer({ settings, onSettings, onSend, busy = false, disabled = false, placeholder }: Props) {
  const info = useQuery(agentInfoQuery())
  const [text, setText] = useState('')
  const [menu, setMenu] = useState<'' | 'model' | 'mode' | 'slash' | 'attach'>('')
  const [note, setNote] = useState('')
  const [attach, setAttach] = useState('')
  const wrap = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  useOutsideClick(wrap, () => setMenu(''), menu !== '')

  const models = info.data?.models ?? []
  const current = models.find((m) => m.value === (settings.model || 'default')) ?? models[0]
  const efforts = current?.supportsEffort ? (current.supportedEffortLevels ?? []) : []
  const modes = (Object.keys(MODE_INFO) as ModeId[]).filter((m) => m !== 'auto' || current?.supportsAutoMode !== false)
  const effortName = settings.effort ? EFFORT_NAMES[settings.effort] ?? settings.effort : '기본'

  const slashHits = useMemo(() => {
    const q = text.startsWith('/') ? text.slice(1).split(/\s/)[0].toLowerCase() : ''
    return (info.data?.commands ?? []).filter((c) => c.name.toLowerCase().includes(q)).slice(0, 40)
  }, [info.data, text])

  useEffect(() => {
    if (!note) return
    const t = setTimeout(() => setNote(''), 4000)
    return () => clearTimeout(t)
  }, [note])

  const pickMode = (m: ModeId) => {
    if (m !== settings.mode) setNote(`${MODE_INFO[settings.mode].name} → ${MODE_INFO[m].name} · 이 세션에 바로 적용돼요.`)
    onSettings({ mode: m })
    setMenu('')
  }
  const pickEffort = (e: string) => {
    onSettings({ effort: e })
    setNote(`Effort ${EFFORT_NAMES[e] ?? e} · 다음 요청부터 적용돼요.`)
  }

  const submit = () => {
    const t = text.trim()
    if (!t || busy || disabled) return
    onSend(t)
    setText('')
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    } else if (e.key === 'Tab' && e.shiftKey) {
      // ⇧ + tab 으로 Mode 를 돌려요
      e.preventDefault()
      const i = modes.indexOf(settings.mode)
      pickMode(modes[(i + 1) % modes.length])
    } else if (e.key === 'Escape') {
      setMenu('')
    }
  }

  // Ultracode — Claude Code 설정이라 xhigh 를 지원하는 모델에서만 (문서: model-config)
  const ultraOk = !!info.data?.ultracode && efforts.includes(info.data.ultracode.needsEffort)
  const ultraRow = ultraOk && (
    <button
      type="button"
      role="switch"
      aria-checked={!!settings.ultracode}
      className={s.ultraRow}
      onClick={() => {
        onSettings({ ultracode: !settings.ultracode })
        setNote(`Ultracode ${settings.ultracode ? '끔' : '켬'} · 다음 요청부터 적용돼요. 켜면 큰 작업을 워크플로로 나눠 돌려서 사용량이 많이 들어요.`)
      }}
    >
      <span className={s.menuText}>
        <span className={s.menuName}>Ultracode</span>
        <span className={s.menuDesc}>큰 작업을 여러 하위 작업으로 나눠 돌려요 · 사용량이 많이 들어요</span>
      </span>
      <span aria-hidden="true" className={s.switchTrack} data-on={!!settings.ultracode}>
        <span className={s.switchKnob} />
      </span>
    </button>
  )

  const effortRow = efforts.length > 0 && (
    <div className={s.effortRow}>
      <span className={s.effortLabel}>
        Effort <span className={s.muted}>({effortName})</span>
      </span>
      <div role="radiogroup" aria-label="Effort" className={s.effortDots}>
        {efforts.map((e) => (
          <button
            key={e}
            type="button"
            role="radio"
            aria-checked={settings.effort === e}
            aria-label={EFFORT_NAMES[e] ?? e}
            title={EFFORT_NAMES[e] ?? e}
            className={s.effortDot}
            data-on={efforts.indexOf(e) <= efforts.indexOf(settings.effort)}
            onClick={() => pickEffort(settings.effort === e ? '' : e)}
          />
        ))}
      </div>
    </div>
  )

  const speech = typeof window !== 'undefined' && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)
  const listen = () => {
    const W = window as unknown as { SpeechRecognition?: new () => SpeechLike; webkitSpeechRecognition?: new () => SpeechLike }
    const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = 'ko-KR'
    rec.onresult = (ev) => setText((t) => (t ? `${t} ` : '') + ev.results[0][0].transcript)
    rec.start()
  }

  return (
    <div ref={wrap} className={s.composerWrap}>
      {note && (
        <span role="status" className={s.modeNote}>
          {note}
        </span>
      )}
      <div className={s.composer}>
        <div className={s.inputRow}>
          <label htmlFor="agent-chat" className={s.srOnly}>
            에이전트에게 요청하기
          </label>
          <textarea
            id="agent-chat"
            ref={area}
            rows={2}
            className={s.textarea}
            value={text}
            disabled={disabled}
            placeholder={placeholder ?? 'Claude 에게 요청하기'}
            onChange={(e) => {
              setText(e.target.value)
              if (e.target.value.startsWith('/') && !e.target.value.includes(' ')) setMenu('slash')
              else if (menu === 'slash') setMenu('')
            }}
            onKeyDown={onKey}
          />
          {speech && (
            <button type="button" aria-label="음성 입력" title="음성 입력" className={s.iconBtn} onClick={listen}>
              🎙
            </button>
          )}
        </div>

        <div className={s.ccRow}>
          <button type="button" aria-label="파일 첨부" title="파일 경로 붙이기" className={s.iconBtn} onClick={() => setMenu(menu === 'attach' ? '' : 'attach')}>
            +
          </button>
          <button
            type="button"
            aria-label="슬래시 명령"
            title="슬래시 명령"
            className={s.iconBtn}
            onClick={() => {
              if (!text.startsWith('/')) setText('/')
              setMenu(menu === 'slash' ? '' : 'slash')
              area.current?.focus()
            }}
          >
            /
          </button>

          <div className={s.ccModel}>
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={menu === 'model'}
              aria-label={`모델: ${chipName(current)}, Effort ${effortName}, 바꾸기`}
              className={s.chipBtn}
              onClick={() => setMenu(menu === 'model' ? '' : 'model')}
            >
              <span>{chipName(current)}</span>
              {efforts.length > 0 && <span className={s.muted}>{effortName}</span>}
              {ultraOk && settings.ultracode && <span className={s.ultraTag}>Ultracode</span>}
            </button>
            {menu === 'model' && (
              <div role="menu" aria-label="모델" className={s.menu}>
                <span className={s.menuTitle}>Select a model</span>
                <div className={s.menuList}>
                  {models.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      role="menuitemradio"
                      aria-checked={m.value === (current?.value ?? '')}
                      className={s.menuItem}
                      onClick={() => {
                        onSettings({ model: m.value === 'default' ? '' : m.value })
                        setMenu('')
                      }}
                    >
                      <span className={s.menuText}>
                        <span className={s.menuName}>{m.displayName}</span>
                        <span className={s.menuDesc}>{m.description}</span>
                      </span>
                      <span aria-hidden="true" className={s.check}>
                        ✓
                      </span>
                    </button>
                  ))}
                  {info.isError && <span className={s.menuDesc}>모델 목록을 못 받았어요 — Claude Code 설치·로그인을 확인해 주세요.</span>}
                </div>
                {effortRow}
                {ultraRow}
              </div>
            )}
          </div>

          <div className={s.ccMode}>
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={menu === 'mode'}
              aria-label={`Mode: ${MODE_INFO[settings.mode].name}, Effort ${effortName}, 바꾸기`}
              className={s.modeBtn}
              onClick={() => setMenu(menu === 'mode' ? '' : 'mode')}
            >
              <span aria-hidden="true">{MODE_INFO[settings.mode].icon}</span>
              <span className={s.ccModeName}>{MODE_INFO[settings.mode].name}</span>
            </button>
            {menu === 'mode' && (
              <div role="menu" aria-label="Mode" className={`${s.menu} ${s.menuRight}`}>
                <div className={s.menuTitleRow}>
                  <span className={s.menuTitle}>Modes</span>
                  <span className={s.muted}>
                    <kbd>⇧</kbd> + <kbd>tab</kbd> to switch
                  </span>
                </div>
                {modes.map((m) => (
                  <button key={m} type="button" role="menuitemradio" aria-checked={settings.mode === m} className={s.menuItem} onClick={() => pickMode(m)}>
                    <span aria-hidden="true" className={s.modeIcon}>
                      {MODE_INFO[m].icon}
                    </span>
                    <span className={s.menuText}>
                      <span className={s.menuName}>{MODE_INFO[m].name}</span>
                      <span className={s.menuDesc}>{MODE_INFO[m].desc}</span>
                    </span>
                    <span aria-hidden="true" className={s.check}>
                      ✓
                    </span>
                  </button>
                ))}
                {effortRow}
                {ultraRow}
              </div>
            )}
          </div>

          <button type="button" aria-label="보내기" className={s.sendBtn} disabled={!text.trim() || busy || disabled} onClick={submit}>
            ↑
          </button>
        </div>

        {menu === 'slash' && slashHits.length > 0 && (
          <div role="menu" aria-label="슬래시 명령" className={`${s.menu} ${s.menuUp}`}>
            <div className={s.menuList}>
              {slashHits.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  role="menuitem"
                  className={s.menuItem}
                  onClick={() => {
                    setText(`/${c.name} `)
                    setMenu('')
                    area.current?.focus()
                  }}
                >
                  <span className={s.menuText}>
                    <span className={s.menuName}>
                      /{c.name} <span className={s.muted}>{c.argumentHint}</span>
                    </span>
                    <span className={s.menuDesc}>{c.description}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {menu === 'attach' && (
          <div className={`${s.menu} ${s.menuUp}`}>
            <span className={s.menuTitle}>파일 경로 붙이기</span>
            <form
              className={s.attachForm}
              onSubmit={(e) => {
                e.preventDefault()
                if (attach.trim()) setText((t) => `${t}${t && !t.endsWith(' ') ? ' ' : ''}@${attach.trim()} `)
                setAttach('')
                setMenu('')
                area.current?.focus()
              }}
            >
              <input className={s.reason} value={attach} onChange={(e) => setAttach(e.target.value)} placeholder="src/train.py" autoFocus />
              <button type="submit" className={s.ghostBtn}>
                붙이기
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}

interface SpeechLike {
  lang: string
  onresult: (ev: { results: { 0: { transcript: string } }[] }) => void
  start: () => void
}
