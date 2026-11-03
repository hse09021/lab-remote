import { useCallback, useRef } from 'react'
import { DiffEditor, Editor, loader, useMonaco } from '@monaco-editor/react'
import * as monacoEditor from 'monaco-editor'
import type { editor } from 'monaco-editor'
import '@/styles/monaco-worker'
import type { CodeFile } from '@/api/types'
import { Button } from '@/components'
import {
  EDITOR_OPTIONS,
  LAB_THEME,
  labTheme,
  languageOf,
} from '@/styles/monaco-theme'
import s from './EditorHost.module.css'

/*
 * @monaco-editor/react 는 기본값으로 jsDelivr CDN에서 monaco를 받아와요.
 * 원격 서버에서 돌리는 도구라 바깥 네트워크에 기대면 안 되고, 글꼴처럼
 * 번들에 넣는 게 맞아요. npm 패키지를 직접 넘겨 CDN 경로를 끊어요.
 */
loader.config({ monaco: monacoEditor })

interface Props {
  file: CodeFile
  /** 커서가 움직일 때마다 상태바에 알려 줘요 */
  onCursor: (pos: { line: number; column: number } | null) => void
}

/**
 * Monaco 편집기. AI가 고친 파일(original이 있는 파일)은 DiffEditor로
 * 바뀐 줄을 바로 보여 주고, 그 밖에는 보통 편집기예요.
 */
export function EditorHost({ file, onCursor }: Props) {
  const monaco = useMonaco()
  const themeReady = useRef(false)

  if (monaco && !themeReady.current) {
    monaco.editor.defineTheme(LAB_THEME, labTheme)
    monaco.editor.setTheme(LAB_THEME)
    themeReady.current = true
  }

  const language = languageOf(file.path)
  const isDiff = file.original !== null

  const attachCursor = useCallback(
    (ed: editor.IStandaloneCodeEditor) => {
      const report = () => {
        const p = ed.getPosition()
        onCursor(p ? { line: p.lineNumber, column: p.column } : null)
      }
      report()
      ed.onDidChangeCursorPosition(report)
    },
    [onCursor],
  )

  return (
    <div className={s.wrap}>
      {file.banner && (
        <div data-tone={file.banner.tone} className={s.banner}>
          <span className={s.bannerTitle}>{file.banner.title}</span>
          <span className={s.bannerText}>{file.banner.text}</span>
          {file.banner.actions.map((a) => (
            <Button key={a} variant="pill">
              {a}
            </Button>
          ))}
        </div>
      )}

      {isDiff ? (
        <DiffEditor
          className={s.editor}
          language={language}
          original={file.original ?? ''}
          modified={file.content}
          theme={LAB_THEME}
          loading={<div className={s.loading}>편집기를 불러오는 중이에요…</div>}
          options={{
            ...EDITOR_OPTIONS,
            // 목업처럼 한 화면에 위아래로 겹쳐 보여 줘요
            renderSideBySide: false,
            readOnly: file.readOnly,
            renderOverviewRuler: false,
          }}
          onMount={(ed) => attachCursor(ed.getModifiedEditor())}
        />
      ) : (
        <Editor
          className={s.editor}
          path={file.path}
          language={language}
          value={file.content}
          theme={LAB_THEME}
          loading={<div className={s.loading}>편집기를 불러오는 중이에요…</div>}
          options={{ ...EDITOR_OPTIONS, readOnly: file.readOnly }}
          onMount={attachCursor}
        />
      )}
    </div>
  )
}
