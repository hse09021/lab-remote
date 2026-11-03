import type { editor } from 'monaco-editor'

/**
 * tokens.css 값을 그대로 옮긴 Monaco 라이트 테마.
 * Monaco는 CSS 변수를 못 읽어서 여기서만 hex를 직접 써요 —
 * 값이 바뀌면 tokens.css 와 함께 고쳐야 해요.
 */
const T = {
  text: '141A19',
  textFaint: '7A8482',
  accentDark: '0B5A4B',
  attentionText: '8A3D09',
  info: '1F5FA8',
  comment: '6B7572',
  purple: '6B3FA0',
  bg: 'FFFFFF',
  border: 'E1E5E4',
  accentRow: 'F6FBF9',
  diffAdd: 'DDF1EA',
  diffDel: 'FCE9E2',
} as const

export const LAB_THEME = 'lab-light'

export const labTheme: editor.IStandaloneThemeData = {
  base: 'vs',
  inherit: true,
  rules: [
    { token: '', foreground: T.text },
    { token: 'comment', foreground: T.comment, fontStyle: 'italic' },
    { token: 'string', foreground: T.attentionText },
    { token: 'string.yaml', foreground: T.attentionText },
    { token: 'number', foreground: T.info },
    { token: 'keyword', foreground: T.purple },
    { token: 'keyword.python', foreground: T.purple },
    // YAML 키 · Python 함수/빌트인 · 마크다운 제목
    { token: 'type', foreground: T.accentDark },
    { token: 'tag', foreground: T.accentDark },
    { token: 'key', foreground: T.accentDark },
    { token: 'identifier.yaml', foreground: T.accentDark },
    { token: 'support.function', foreground: T.accentDark },
    { token: 'keyword.md', foreground: T.accentDark, fontStyle: 'bold' },
  ],
  colors: {
    'editor.background': `#${T.bg}`,
    'editor.foreground': `#${T.text}`,
    'editorLineNumber.foreground': `#${T.textFaint}`,
    'editorLineNumber.activeForeground': `#${T.text}`,
    'editor.lineHighlightBackground': `#${T.accentRow}`,
    'editorIndentGuide.background1': `#${T.border}`,
    'editorGutter.background': `#${T.bg}`,
    'diffEditor.insertedTextBackground': `#${T.diffAdd}80`,
    'diffEditor.removedTextBackground': `#${T.diffDel}80`,
    'diffEditor.insertedLineBackground': `#${T.diffAdd}`,
    'diffEditor.removedLineBackground': `#${T.diffDel}`,
  },
}

/** 목업의 편집기 치수를 그대로 옮긴 공통 옵션 */
export const EDITOR_OPTIONS: editor.IStandaloneEditorConstructionOptions = {
  fontFamily: "'Roboto Mono', monospace",
  fontSize: 13,
  lineHeight: 24,
  lineNumbersMinChars: 3,
  lineDecorationsWidth: 18,
  glyphMargin: false,
  folding: false,
  renderLineHighlight: 'none',
  scrollBeyondLastLine: false,
  minimap: { enabled: true, maxColumn: 64, renderCharacters: false },
  padding: { top: 4, bottom: 16 },
  automaticLayout: true,
  tabSize: 2,
  scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
}

/** 파일 확장자로 Monaco 언어를 정해요 */
export function languageOf(path: string): string {
  const ext = path.slice(path.lastIndexOf('.') + 1).toLowerCase()
  switch (ext) {
    case 'yaml':
    case 'yml':
      return 'yaml'
    case 'py':
      return 'python'
    case 'md':
      return 'markdown'
    case 'json':
      return 'json'
    default:
      return 'plaintext'
  }
}

/** 상태바에 보여 줄 언어 이름 */
export function languageLabel(lang: string): string {
  switch (lang) {
    case 'yaml':
      return 'YAML'
    case 'python':
      return 'Python'
    case 'markdown':
      return 'Markdown'
    case 'json':
      return 'JSON'
    default:
      return '일반 텍스트'
  }
}
