import type {
  Dashboard,
  DesignDraft,
  EventEntry,
  Experiment,
  Paper,
  PermissionsPayload,
} from '../types'
import {
  overlayPapers,
  readLoopPaused,
  readStopped,
  readDesignValues,
  readDiscrepancy,
  readPermissions,
} from '../mockStore'

/**
 * mock JSON(처음 상태) 위에 저장소의 내 값을 덮어요.
 * 화면은 이걸 거쳐 나온 값만 보기 때문에, 다른 화면에 갔다 와도
 * (쿼리 캐시가 비워져도) 바꾼 값이 그대로예요.
 */
export function applyOverlay<T>(path: string, data: T): T {
  if (path === '/papers') {
    return overlayPapers(data as Paper[]) as T
  }

  if (path === '/experiments') {
    const stopped = readStopped()
    if (!stopped.length) return data
    return (data as Experiment[]).map((e) =>
      stopped.includes(e.id)
        ? { ...e, state: 'stopped' as const, stateNote: '모바일에서 정지', progress: null }
        : e,
    ) as T
  }

  if (path === '/experiments/events') {
    const stopped = readStopped()
    if (!stopped.length) return data
    // 정지한 실험을 기록 맨 위에 올려요 (목업과 같게)
    const added: EventEntry[] = stopped.map((id) => ({
      time: '방금',
      kind: '정지',
      tone: 'warn',
      text: `${id} 정지 · 체크포인트 저장 · 모바일에서 요청`,
    }))
    return [...added, ...(data as EventEntry[])] as T
  }

  if (path === '/experiments/dashboard') {
    return { ...(data as Dashboard), loopPaused: readLoopPaused() } as T
  }

  if (path === '/experiments/permissions') {
    return { ...(data as PermissionsPayload), saved: readPermissions() } as T
  }

  const design = path.match(/^\/papers\/([^/]+)\/design$/)
  if (design) {
    return { ...(data as DesignDraft), saved: readDesignValues(design[1]) } as T
  }

  const reader = path.match(/^\/papers\/([^/]+)\/reader$/)
  if (reader) {
    const payload = data as { discrepancy: { chosen: string | null } }
    return {
      ...payload,
      discrepancy: { ...payload.discrepancy, chosen: readDiscrepancy(reader[1]) },
    } as T
  }

  return data
}
