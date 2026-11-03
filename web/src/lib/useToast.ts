import { useCallback, useEffect, useRef, useState } from 'react'
import type { ToastAction } from '@/components/Toast'

/**
 * 토스트 한 개를 보여 주고 시간이 지나면 지워요.
 * 목업은 componentWillUnmount가 없어서 타이머가 남았는데, 여기서는 정리해요.
 */
export function useToast(durationMs = 2400) {
  const [message, setMessage] = useState('')
  const [action, setAction] = useState<ToastAction | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setMessage('')
    setAction(null)
  }, [])

  const show = useCallback(
    (text: string, opts?: { action?: ToastAction; durationMs?: number }) => {
      if (timer.current) clearTimeout(timer.current)
      setMessage(text)
      setAction(opts?.action ?? null)
      timer.current = setTimeout(
        () => {
          timer.current = null
          setMessage('')
          setAction(null)
        },
        opts?.durationMs ?? durationMs,
      )
    },
    [durationMs],
  )

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  return { message, action, show, clear, visible: message !== '' }
}
