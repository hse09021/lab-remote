import type { RefObject } from 'react'
import type { PaperReaderPayload } from '@/api/types'
import { CiteCard } from './CiteCard'
import { FloatingChat } from './FloatingChat'
import { MyHighlightMenu } from './MyHighlightMenu'
import { NotePopover, SelectionMenu, TranslatePopover } from './SelectionMenu'
import type { SelectionAction, SelectionAnchor } from './SelectionMenu'
import type { UserAnnotation } from '@/api/annotations'
import type { useFloatingChat } from './useFloatingChat'
import type { useReaderOverlays } from './useReaderOverlays'

export interface FloatingHandlers {
  /** 대화창 본체를 띄울 곳 — 스크롤하지 않는 가운데 열 */
  chatHost: RefObject<HTMLElement | null>
  chat: ReturnType<typeof useFloatingChat>
  overlays: ReturnType<typeof useReaderOverlays>
  reader: PaperReaderPayload
  /** 실시간 번역 (vault 논문) — 선택한 텍스트가 같을 때만 */
  liveTranslation?: { text: string; translation: string | null; note: string | null } | null
  onSelectionAct: (a: SelectionAction) => void
  onJump: (sectionId: string) => void
  onOpenPaper: (title: string) => void
  onSaveRef: (n: number) => void
  /** 라이브러리에 들어 있는지 — papers 캐시에서 봐요 */
  isRefSaved: (r: { n: number; arxiv: string | null }) => boolean
  /** 선택한 텍스트가 이미 내 하이라이트인지 (저장소에서 봐요) */
  isMine: (text: string) => boolean
  /** 본문에서 내 하이라이트를 눌렀을 때 뜨는 메뉴 */
  myMenu: { annotation: UserAnnotation; anchor: SelectionAnchor } | null
  onMyMenuAnnotate: () => void
  onMyMenuDelete: () => void
  onMyMenuClose: () => void
  /** 주석 팝오버 저장 — 위치 라벨 계산이 필요해서 화면이 맡아요 */
  onSaveNote: (body: string) => void
  onWorth: (n: number) => void
  onToast: (msg: string) => void
}

/**
 * 본문 위에 뜨는 것들 — 대화창 · 인용 카드 · 선택 메뉴 · 팝오버.
 * 스크롤 컨테이너 안에 넣어서 본문과 함께 움직여요.
 * 대화창 본체만 예외로 `chatHost`(가운데 열)에 포털해서 모서리에 고정돼요.
 */
export function FloatingLayer({
  liveTranslation = null,
  chatHost,
  chat,
  overlays,
  reader,
  onSelectionAct,
  onJump,
  onOpenPaper,
  onSaveRef,
  isRefSaved,
  isMine,
  myMenu,
  onMyMenuAnnotate,
  onMyMenuDelete,
  onMyMenuClose,
  onSaveNote,
  onWorth,
  onToast,
}: FloatingHandlers) {
  const citeRef = overlays.cite
    ? reader.references.find((r) => r.n === overlays.cite!.n)
    : undefined


  return (
    <>
      {overlays.selection && (
        <SelectionMenu
          anchor={overlays.selection.anchor}
          highlighted={isMine(overlays.selection.text)}
          onAct={onSelectionAct}
        />
      )}

      {overlays.popover?.kind === 'translate' && (
        <TranslatePopover
          anchor={overlays.popover.anchor}
          source={overlays.popover.text}
          translation={
            liveTranslation && liveTranslation.text === overlays.popover.text
              ? (liveTranslation.translation ?? '번역하는 중이에요…')
              : overlays.popover.text === reader.selectionSpot.text
                ? reader.selectionSpot.translation
                : null
          }
          note={
            liveTranslation && liveTranslation.text === overlays.popover.text
              ? liveTranslation.note
              : overlays.popover.text === reader.selectionSpot.text
                ? reader.selectionSpot.translationNote
                : null
          }
          onClose={() => overlays.setPopover(null)}
        />
      )}

      {overlays.popover?.kind === 'note' && (
        <NotePopover
          anchor={overlays.popover.anchor}
          onSave={onSaveNote}
          onClose={() => overlays.setPopover(null)}
        />
      )}

      {myMenu && (
        <MyHighlightMenu
          annotation={myMenu.annotation}
          anchor={myMenu.anchor}
          onAnnotate={onMyMenuAnnotate}
          onDelete={onMyMenuDelete}
          onClose={onMyMenuClose}
        />
      )}

      {citeRef && overlays.cite && (
        <CiteCard
          reference={citeRef}
          anchor={overlays.cite.anchor}
          saved={isRefSaved(citeRef)}
          onSave={() => onSaveRef(citeRef.n)}
          onClose={() => overlays.closeAll()}
          onWorth={() => onWorth(citeRef.n)}
          onToast={onToast}
        />
      )}

      <FloatingChat
        host={chatHost}
        state={chat.state}
        topic={chat.topic}
        terms={reader.terms}
        onClose={chat.close}
        onClear={chat.clearLog}
        onMinimize={chat.minimize}
        onRestore={chat.restore}
        onAsk={chat.ask}
        onJump={onJump}
        onOpenPaper={onOpenPaper}
      />
    </>
  )
}
