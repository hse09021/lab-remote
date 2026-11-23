/**
 * Monaco 웹 워커를 번들에서 가져와요 (CDN 대신).
 * import하는 것만으로 self.MonacoEnvironment가 설정돼요.
 */
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'

self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    if (label === 'json') return new jsonWorker()
    // yaml · python · markdown은 전용 워커가 없어 기본 워커를 써요
    return new editorWorker()
  },
}
