import { useNavigate } from 'react-router-dom'
import { Button } from '@/components'
import s from './ScreenPlaceholder.module.css'

export default function NotFound() {
  const navigate = useNavigate()
  return (
    <main className={s.screen}>
      <h1 className={s.title}>없는 화면이에요</h1>
      <p className={s.note}>주소를 다시 확인해 주세요.</p>
      <div>
        <Button variant="primary" onClick={() => navigate('/experiments')}>
          실험으로 가기
        </Button>
      </div>
    </main>
  )
}
