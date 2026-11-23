import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { useSetVault, vaultQuery } from '@/api/papers'
import { Dialog, dialogStyles as ds } from '@/components'

/**
 * vault 위치 정하기 (8단계). lab.remote는 vault를 **읽기만** 해요 —
 * 노트 파일을 고치지 않고, 읽음 상태는 데이터 폴더에 따로 둬요.
 */
export function VaultDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const info = useQuery({ ...vaultQuery(), enabled: open })
  const save = useSetVault()
  const [path, setPath] = useState('')

  useEffect(() => {
    if (open && info.data) setPath(info.data.custom ? info.data.path : '')
  }, [open, info.data])

  const err = save.error instanceof ApiError ? save.error.message : save.error ? String(save.error) : undefined

  return (
    <Dialog
      open={open}
      title="vault 위치"
      confirmLabel="저장"
      busy={save.isPending}
      error={err}
      onClose={() => {
        save.reset()
        onClose()
      }}
      onConfirm={() => save.mutate(path.trim(), { onSuccess: onClose })}
    >
      <p style={{ margin: 0 }}>
        Obsidian vault 폴더를 적어 주세요. <code>Papers/</code> 안의 MD가 논문 노트, 나머지 MD는 내 메모예요. 비우면 데이터 폴더의{' '}
        <code>vault/</code>를 써요.
      </p>
      <label className={ds.field}>
        폴더 경로
        <input
          className={ds.input}
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder={info.data && !info.data.custom ? info.data.path : '~/Documents/vault'}
          autoFocus
        />
      </label>
      {info.data && (
        <p style={{ margin: 0 }}>
          지금: {info.data.exists ? `논문 ${info.data.papers} · 메모 ${info.data.notes}` : '폴더가 아직 없어요'}
        </p>
      )}
      <p style={{ margin: 0 }}>lab.remote는 vault를 읽기만 해요. 노트 파일은 고치지 않아요.</p>
    </Dialog>
  )
}
