import type { DesignDraft, Paper, PermissionsPayload } from '../types'
import {
  overlayPapers,
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
