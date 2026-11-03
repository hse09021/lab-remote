import clsx from 'clsx'
import s from './ScreenPlaceholder.module.css'

interface Props {
  title: string
  /** 제목을 mono로 (실험 이름 등) */
  mono?: boolean
  /** 어느 목업을 옮길 자리인지 */
  mockup: string
  note?: string
}

/**
 * 1단계에서는 라우팅과 껍데기만 확인하므로 각 화면은 제목만 있어요.
 * 2단계에서 목업 순서대로 하나씩 채워요.
 */
export function ScreenPlaceholder({ title, mono = false, mockup, note }: Props) {
  return (
    <main className={s.screen}>
      <h1 className={clsx(s.title, mono && s.mono)}>{title}</h1>
      {note && <p className={s.note}>{note}</p>}
      <p className={s.source}>docs/mockups/{mockup}</p>
    </main>
  )
}
