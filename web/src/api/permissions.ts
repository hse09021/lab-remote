import { useMutation, useQueryClient } from '@tanstack/react-query'
import { send } from './client'
import type { Permission, PermissionMode } from './types'

/**
 * 권한 설정 저장.
 * 목업 모드에서도 저장소에 남아 다른 화면·새로 고침 뒤에도 그대로예요.
 */
export function useSavePermissions() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (value: { mode: PermissionMode; overrides: Record<string, Permission> }) =>
      send<unknown>('PUT', '/experiments/permissions', value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['experiments', 'permissions'] }),
  })
}
