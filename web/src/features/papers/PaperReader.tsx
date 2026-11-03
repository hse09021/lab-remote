import { useParams } from 'react-router-dom'
import { ScreenPlaceholder } from '../ScreenPlaceholder'

export default function PaperReader() {
  const { id } = useParams<{ id: string }>()
  return (
    <ScreenPlaceholder
      title="논문 리더"
      mockup="FocusReader.dc.html"
      note={`아웃라인 · 본문(PDF/HTML) · AI 패널 — 논문 ${id ?? '(없음)'}`}
    />
  )
}
