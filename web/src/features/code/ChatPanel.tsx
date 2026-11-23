import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { CodeChatPayload } from '@/api/types'
import { IconButton, LoadingState, PanelIcon, TagChip, VisuallyHidden } from '@/components'
import s from './ChatPanel.module.css'

interface Props {
  style: CSSProperties
  chat: CodeChatPayload | undefined
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
  fileLabel,
  attachment,
  onRemoveAttachment,
  onCollapse,
}: Props) {
  const [draft, setDraft] = useState('')

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
              {/* Mode·모델 메뉴는 3단계에서 SDK 로 확인한 값으로 붙어요 (PLAN 5장) */}
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
