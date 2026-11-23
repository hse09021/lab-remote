import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { terminalSocketUrl } from '@/api/ide'
import s from './Ide.module.css'

/** 디자인 토큰을 xterm 색으로 (xterm 은 CSS 변수를 못 읽어요) */
function tokenColors() {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return {
    background: v('--surface-muted'),
    foreground: v('--text'),
    cursor: v('--accent'),
    selectionBackground: v('--accent-tint'),
    black: v('--text'),
    green: v('--accent'),
    yellow: v('--attention'),
    red: v('--diff-del-text'),
    blue: v('--info'),
    magenta: v('--purple'),
    brightBlack: v('--text-faint'),
  }
}

/**
 * 터미널 하나 — WebSocket ↔ tmux. 탭을 닫거나 브라우저를 닫아도 tmux 세션(셸·학습)은
 * 데스크톱에 남아요. 다시 열면 그대로 붙어요.
 */
export function TerminalView({ project, name, run, write = false }: { project: string; name?: string; run?: string; write?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [error, setError] = useState('')

  useEffect(() => {
    const el = host.current
    if (!el) return
    const term = new Terminal({
      // 한글은 두 칸 너비로 그려요 (터미널 규칙)
      fontFamily: `${getComputedStyle(document.documentElement).getPropertyValue('--font-mono').trim() || 'monospace'}, ${getComputedStyle(document.documentElement).getPropertyValue('--font-sans').trim()}`,
      fontSize: 13,
      theme: tokenColors(),
      cursorBlink: true,
      scrollback: 5000,
      disableStdin: !!run && !write,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(el)
    fit.fit()

    const ws = new WebSocket(terminalSocketUrl({ project, name, run, write, cols: term.cols, rows: term.rows }))
    ws.binaryType = 'arraybuffer'
    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }
    ws.onopen = () => {
      setStatus('open')
      sendResize()
      term.focus()
    }
    ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        try {
          const msg = JSON.parse(e.data) as { type: string; message?: string }
          if (msg.type === 'error') setError(msg.message ?? '터미널에 붙지 못했어요.')
        } catch {
          term.write(e.data)
        }
        return
      }
      term.write(new Uint8Array(e.data as ArrayBuffer))
    }
    ws.onclose = () => setStatus('closed')
    const input = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
    })
    const observer = new ResizeObserver(() => {
      try {
        fit.fit()
        sendResize()
      } catch {
        // 숨겨진 탭이면 크기가 0 이에요
      }
    })
    observer.observe(el)
    return () => {
      observer.disconnect()
      input.dispose()
      ws.close()
      term.dispose()
    }
  }, [project, name, run, write])

  return (
    <div className={s.termWrap}>
      {(status !== 'open' || error) && (
        <div className={s.termStatus} data-tone={error || status === 'closed' ? 'warn' : undefined}>
          {error || (status === 'connecting' ? '붙는 중이에요…' : '연결이 끊겼어요. 탭을 다시 열면 그대로 붙어요 (셸은 데스크톱에서 계속 돌아요).')}
        </div>
      )}
      {run && !write && <div className={s.termNote}>학습 실행 보기 전용 · 잘못 누른 Ctrl+C 로 멈추지 않게 입력을 막아 뒀어요</div>}
      <div ref={host} className={s.term} />
    </div>
  )
}
