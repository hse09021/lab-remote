import type { Experiment } from '@/api/types'
import type { PillTone } from '@/components'

/**
 * 목업은 상태 칩의 글자와 색이 마크업에 박혀 있었어요.
 * 여기서는 실험 데이터에서 계산해요.
 */
export function experimentStatus(exp: Experiment): { label: string; tone: PillTone } {
  switch (exp.state) {
    case 'queued':
      return { label: `대기 ${exp.queuePosition ?? ''}`.trim(), tone: 'neutral' }
    case 'running':
      return {
        label: exp.progress === null ? '실행 중' : `실행 중 ${exp.progress}%`,
        tone: 'success',
      }
    case 'done':
      return { label: '완료', tone: 'solid' }
    case 'failed':
      return { label: exp.stateNote ? `실패 · ${exp.stateNote}` : '실패', tone: 'warn' }
    case 'stopped':
      return { label: '정지됨', tone: 'warn' }
  }
}
