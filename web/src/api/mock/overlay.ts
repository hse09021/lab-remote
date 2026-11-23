import type {
  Dashboard,
  FileNode,
  EventEntry,
  Experiment,
  Paper,
} from '../types'
import {
  overlayPapers,
  readFileOps,
  readLoopPaused,
  readStopped,
  readDiscrepancy,
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

  if (path === '/code/tree') {
    return applyFileOps(data as FileNode, '') as T
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

/**
 * 탐색기에서 한 작업(만들기·이름 바꾸기·삭제)을 트리에 덮어요.
 * 경로는 루트를 뺀 '/' 이어 붙인 전체 경로예요.
 */
function applyFileOps(node: FileNode, parentPath: string): FileNode {
  const ops = readFileOps()
  const path = parentPath ? `${parentPath}/${node.name}` : node.name
  const name = ops.renamed[path] ?? node.name
  const self = { ...node, name }

  if (node.kind !== 'dir') return self

  const kept = (node.children ?? [])
    .filter((c) => !ops.deleted.includes(`${path}/${c.name}`))
    .map((c) => applyFileOps(c, path))

  const added: FileNode[] = ops.created
    .filter((c) => c.path.startsWith(`${path}/`) && !c.path.slice(path.length + 1).includes('/'))
    .map((c) => ({
      // 이름을 바꾸면 created 의 경로 자체가 옮겨져요 (mockStore.renameNode)
      name: c.path.slice(path.length + 1),
      kind: c.kind,
      gitStatus: 'U' as const,
      ...(c.kind === 'dir' ? { children: [], open: false } : {}),
    }))

  return { ...self, children: [...added, ...kept] }
}
