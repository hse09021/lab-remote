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
      'math', 'mi', 'mo', 'mn', 'mrow', 'msub', 'msup', 'mfrac', 'msqrt',
    ],
    ALLOWED_ATTR: [
      'id', 'class', 'style', 'colspan', 'rowspan', 'scope',
      'src', 'alt', 'width', 'height', 'loading',
      'href', 'target', 'rel', 'type',
      'data-section', 'data-explain', 'data-cite',
    ],
    // 바깥 주소로 나가는 건 막아요 (이미지는 같은 출처 fixtures 만)
    ALLOWED_URI_REGEXP: /^(?:\/|#)/,
    ADD_ATTR: ['data-section', 'data-explain', 'data-cite'],
  })
}
