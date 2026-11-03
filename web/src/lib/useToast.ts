import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 토스트 한 개를 보여 주고 시간이 지나면 지워요.
 * 목업은 componentWillUnmount가 없어서 타이머가 남았는데, 여기서는 정리해요.
 */
export function useToast(durationMs = 2400) {
  const [message, setMessage] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setMessage('')
  }, [])

  const show = useCallback(
    (text: string) => {
      if (timer.current) clearTimeout(timer.current)
      setMessage(text)
      timer.current = setTimeout(() => {
        timer.current = null
        setMessage('')
      }, durationMs)
    },
    [durationMs],
  )

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  return { message, show, clear, visible: message !== '' }
}
