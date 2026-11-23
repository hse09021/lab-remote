import { useEffect, useRef } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Button } from './Button'
import s from './Dialog.module.css'

interface Props {
  open: boolean
  title: string
  children?: ReactNode
  /** 확인 버튼 글자 — 짧은 동사 */
  confirmLabel: string
  tone?: 'accent' | 'danger'
  busy?: boolean
  error?: string
  onConfirm: () => void
  onClose: () => void
}

/**
 * 한 번 더 묻는 창. 브라우저의 `<dialog>`를 써서 포커스 가두기·Esc 닫기를
 * 그대로 얻어요. 안의 입력칸에서 Enter를 누르면 확인과 같아요.
 */
export function Dialog({
  open,
  title,
  children,
  confirmLabel,
  tone = 'accent',
  busy = false,
  error,
  onConfirm,
  onClose,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!busy) onConfirm()
  }

  return (
    <dialog ref={ref} className={s.dialog} onClose={onClose} aria-labelledby="dlg-title">
      <form method="dialog" onSubmit={submit} className={s.form}>
        <h2 id="dlg-title" className={s.title}>
          {title}
        </h2>
        <div className={s.body}>{children}</div>
        {error && (
          <p role="alert" className={s.error}>
            {error}
          </p>
        )}
        <div className={s.actions}>
          <Button type="button" size="md" variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button type="submit" size="md" variant={tone === 'danger' ? 'danger' : 'accent'} disabled={busy}>
            {busy ? '하는 중…' : confirmLabel}
          </Button>
        </div>
      </form>
    </dialog>
  )
}
