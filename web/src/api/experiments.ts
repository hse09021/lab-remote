import { queryOptions } from '@tanstack/react-query'
import { get } from './client'
import type {
  Dashboard,
  EventEntry,
  Experiment,
  PermissionsPayload,
  ProjectsPayload,
} from './types'

/**
 * 실험 화면이 쓰는 쿼리들.
 * 화면은 mock JSON을 직접 import하지 않고 이 헬퍼만 써요 — FastAPI로 바꿀 때
 * client.ts 한 곳만 고치면 되도록요.
 */

export const projectsQuery = () =>
  queryOptions({
    queryKey: ['projects'],
    queryFn: () => get<ProjectsPayload>('/projects'),
  })

export const dashboardQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'dashboard'],
    queryFn: () => get<Dashboard>('/experiments/dashboard'),
  })

export const experimentsQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'list'],
    queryFn: () => get<Experiment[]>('/experiments'),
  })

export const eventsQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'events'],
    queryFn: () => get<EventEntry[]>('/experiments/events'),
  })

export const permissionsQuery = () =>
  queryOptions({
    queryKey: ['experiments', 'permissions'],
    queryFn: () => get<PermissionsPayload>('/experiments/permissions'),
  })
