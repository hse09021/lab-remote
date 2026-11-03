import { useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import type {
  CodeChatPayload,
  PermissionMode,
  PermissionModeOption,
} from '@/api/types'
import { IconButton, LoadingState, PanelIcon, TagChip, VisuallyHidden } from '@/components'
import { useOutsideClick } from '@/lib/useOutsideClick'
import s from './ChatPanel.module.css'

interface Props {
  style: CSSProperties
  chat: CodeChatPayload | undefined
  modes: PermissionModeOption[] | undefined
  /** 입력창에 맥락으로 붙는 현재 파일 */
  fileLabel: string
  /** 탐색기에서 "채팅에 추가" 한 것 */
  attachment: string | null
  onRemoveAttachment: () => void
  onCollapse: () => void
}

export function ChatPanel({
  style,
  chat,
  modes,
  fileLabel,
  attachment,
  onRemoveAttachment,
  onCollapse,
}: Props) {
  const [mode, setMode] = useState<PermissionMode>('full')
  const [prevMode, setPrevMode] = useState<PermissionMode | null>(null)
  const [draft, setDraft] = useState('')

  const current = modes?.find((m) => m.id === mode)
  const previous = modes?.find((m) => m.id === prevMode)

  return (
    <aside aria-label="Claude Code" style={style} className={s.panel}>
      <div className={s.head}>
        <span className={s.name}>Claude Code</span>
        <TagChip>● 연결됨</TagChip>
        <IconButton
          label="Claude Code 패널 접기"
          aria-expanded
          size={34}
          className={s.right}
          onClick={onCollapse}
        >
          <PanelIcon side="right" />
        </IconButton>
        <IconButton label="세션 기록" size={34}>
          <HistoryIcon />
        </IconButton>
        <IconButton label="새 세션" size={34}>
          <PlusIcon />
        </IconButton>
      </div>

      {chat ? (
        <>
          <div className={s.session}>{chat.session}</div>
          <div className={s.list}>
            {chat.messages.map((m, i) => (
              <Message key={i} node={m} />
            ))}
          </div>
        </>
      ) : (
        <LoadingState label="세션을 불러오는 중이에요…" />
      )}

      <div className={s.composerWrap}>
        <div className={s.composer}>
          {previous && current && previous.id !== current.id && (
            <div role="status" className={s.modeNote}>
              {previous.name} → {current.name} · 지금 실행 중인 EXP-007은 그대로 두고 다음
              작업부터 적용해요. 변경 내역은 Decision_log.md에 남겨요.
            </div>
          )}

          <VisuallyHidden>
            <label htmlFor="code-chat">Claude Code에 요청</label>
          </VisuallyHidden>
          <textarea
            id="code-chat"
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="무엇을 할까요?"
            className={s.textarea}
          />

          <div className={s.toolbar}>
            <IconButton label="파일 첨부" size={32}>
              <ClipIcon />
            </IconButton>
            <span className={s.fileChip}>
              <span className={s.fileChipName}>{fileLabel}</span>
              <span aria-hidden="true">×</span>
            </span>
            {attachment && (
              <span className={s.fileChip}>
                <span className={s.fileChipName}>{attachment}</span>
                <button
                  type="button"
                  aria-label={`${attachment} 첨부 빼기`}
                  onClick={onRemoveAttachment}
                  className={s.fileChipRemove}
                >
                  ×
                </button>
              </span>
            )}
            <div className={s.right}>
              <PresetButton
                modes={modes}
                mode={mode}
                onChange={(next) => {
                  if (next === mode) return
                  setPrevMode(mode)
                  setMode(next)
                }}
              />
              <IconButton label="보내기" size={34} variant="primary">
                <SendIcon />
              </IconButton>
            </div>
          </div>
        </div>
      </div>
    </aside>
  )
}

/* ── 권한 프리셋 ──────────────────────────────────────────── */

function PresetButton({
  modes,
  mode,
  onChange,
}: {
  modes: PermissionModeOption[] | undefined
  mode: PermissionMode
  onChange: (m: PermissionMode) => void
}) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useOutsideClick(wrap, () => setOpen(false), open)

  const current = modes?.find((m) => m.id === mode)

  return (
    <div ref={wrap} className={s.presetWrap}>
      <button
        type="button"
        data-mode={mode}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`권한 프리셋: ${current?.name ?? ''}, 바꾸기`}
        onClick={() => setOpen((v) => !v)}
        className={s.preset}
      >
        <ShieldIcon />
        {current?.name ?? '권한 프리셋'}
        <span aria-hidden="true">▾</span>
      </button>

      {open && modes && (
        <div role="menu" aria-label="권한 프리셋" className={s.presetMenu}>
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              role="menuitemradio"
              aria-checked={m.id === mode}
              onClick={() => {
                onChange(m.id)
                setOpen(false)
              }}
              className={s.presetItem}
            >
              <span aria-hidden="true" className={s.presetRadio} />
              <span className={s.presetCol}>
                <span className={s.presetName}>{m.name}</span>
                <span className={s.presetDesc}>{m.desc}</span>
              </span>
            </button>
          ))}
          <span className={s.presetFoot}>
            잠긴 항목 3개는 어떤 프리셋이든 항상 막혀요.{' '}
            <Link to="/experiments/permissions">권한 설정</Link>
          </span>
        </div>
      )}
    </div>
  )
}

/* ── 메시지 ───────────────────────────────────────────────── */

function Message({ node }: { node: CodeChatPayload['messages'][number] }) {
  switch (node.kind) {
    case 'user':
      return <div className={s.user}>{node.text}</div>
    case 'assistant':
      return (
        <div className={s.assistant}>
          <span>{node.text}</span>
          {node.sources && (
            <div className={s.sources}>
              {node.sources.map((src) => (
                <TagChip key={src}>{src}</TagChip>
              ))}
            </div>
          )}
        </div>
      )
    case 'tool':
      return (
        <div className={s.tool}>
          <div className={s.toolHead}>
            <span className={s.toolName}>{node.tool}</span>
            <span className={s.toolPath}>{node.path}</span>
            <span className={s.added}>+{node.added}</span>
            <span className={s.removed}>−{node.removed}</span>
          </div>
          <div className={s.toolBody}>{node.text}</div>
        </div>
      )
    case 'approval':
      return (
        <div className={s.approval}>
          <span className={s.approvalTitle}>{node.title}</span>
          <span className={s.approvalText}>{node.text}</span>
        </div>
      )
  }
}

/* ── 아이콘 ───────────────────────────────────────────────── */

const st = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

const ShieldIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" />
  </svg>
)
const HistoryIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M3 12a9 9 0 103-6.7L3 8" />
    <path d="M3 3v5h5M12 7v5l3 2" />
  </svg>
)
const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
)
const ClipIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M21 11l-8.5 8.5a5 5 0 01-7-7L14 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L15 7" />
  </svg>
)
const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...st} aria-hidden="true">
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
)
