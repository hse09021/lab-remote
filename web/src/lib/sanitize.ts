import DOMPurify from 'dompurify'

/**
 * 바깥에서 온 논문 HTML을 주입하기 전에 정리해요.
 * arXiv HTML 도, 개발용 샘플도 똑같이 이 길을 지나요.
 */
export function sanitizePaperHtml(raw: string): string {
  return DOMPurify.sanitize(raw, {
    // 표·수식·그림 구조와 앵커만 남기면 돼요
    ALLOWED_TAGS: [
      'article', 'section', 'header', 'aside', 'div', 'span', 'p', 'em', 'strong',
      'sub', 'sup', 'br', 'hr',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ol', 'ul', 'li', 'dl', 'dt', 'dd',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'figure', 'figcaption', 'img', 'button', 'a',
      'math', 'mi', 'mo', 'mn', 'mrow', 'msub', 'msup', 'msubsup',
      'mfrac', 'msqrt', 'mroot', 'mtext', 'mspace', 'mover', 'munder',
      'mtable', 'mtr', 'mtd', 'semantics', 'annotation',
    ],
    ALLOWED_ATTR: [
      'id', 'class', 'style', 'colspan', 'rowspan', 'scope',
      'src', 'alt', 'width', 'height', 'loading',
      'href', 'target', 'rel', 'type',
      'data-section', 'data-explain', 'data-cite',
      // MathML
      'xmlns', 'display', 'mathvariant', 'encoding', 'columnalign', 'rowspacing', 'columnspacing',
    ],
    /*
     * 바깥 주소로 나가는 건 막아요 (이미지는 같은 출처 fixtures 만).
     * DOMPurify 는 URI-safe로 알려진 속성(alt·class·id·style·title·xmlns …)이
     * 아니면 **모든** 속성 값을 이 정규식으로 검사해서 떨어뜨려요.
     * 그래서 주소가 아닌 구조 속성은 아래 ADD_URI_SAFE_ATTR로 빼 둬야 해요.
     */
    ALLOWED_URI_REGEXP: /^(?:\/|#)/,
    ADD_URI_SAFE_ATTR: [
      'colspan', 'rowspan', 'scope', 'width', 'height', 'loading', 'target', 'rel', 'type',
      // MathML
      'display', 'mathvariant', 'encoding', 'columnalign', 'rowspacing', 'columnspacing',
    ],
    ADD_ATTR: ['data-section', 'data-explain', 'data-cite'],
    /*
     * USE_PROFILES 는 위에서 쓴 ALLOWED_TAGS·ALLOWED_ATTR 를 통째로 덮어써요
     * (DOMPurify _parseConfig). 좁은 허용 목록을 쓰려면 넣지 않아야 해요.
     * MathML 네임스페이스는 프로필과 무관하게 math* 태그에 허용돼요.
     */
  })
}
