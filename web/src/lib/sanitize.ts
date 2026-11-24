import DOMPurify from 'dompurify'

/**
 * 바깥에서 온 논문 HTML을 주입하기 전에 정리해요.
 * arXiv HTML도, 개발용 샘플도 똑같이 이 길을 지나요.
 */
/*
 * 참고문헌 안의 바깥 링크(arXiv · DOI 등)는 살려서 새 탭으로 열어요.
 * 그림 주소는 같은 서버(`/api/...`)만 — 바깥 그림은 불러오지 않아요.
 */
let hooked = false
function ensureHooks() {
  if (hooked) return
  hooked = true
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (!(node instanceof Element)) return
    if (node.tagName === 'IMG') {
      const src = node.getAttribute('src') ?? ''
      if (!src.startsWith('/')) node.removeAttribute('src')
    }
    if (node.tagName === 'A') {
      const href = node.getAttribute('href') ?? ''
      if (/^https?:/i.test(href)) {
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noopener noreferrer')
      }
    }
  })
}

export function sanitizePaperHtml(raw: string): string {
  ensureHooks()
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
      // arXiv(LaTeXML)가 쓰는 나머지 MathML
      'mstyle', 'mpadded', 'mphantom', 'menclose', 'munderover', 'mmultiscripts', 'mprescripts', 'none',
      'mlabeledtr', 'merror', 'annotation-xml', 'cite',
    ],
    ALLOWED_ATTR: [
      'id', 'class', 'style', 'colspan', 'rowspan', 'scope',
      'src', 'alt', 'width', 'height', 'loading',
      'href', 'target', 'rel', 'type',
      'data-section', 'data-explain', 'data-cite',
      // MathML
      'xmlns', 'display', 'mathvariant', 'encoding', 'columnalign', 'rowspacing', 'columnspacing',
      'alttext', 'stretchy', 'fence', 'separator', 'lspace', 'rspace', 'accent', 'accentunder',
      'largeop', 'movablelimits', 'symmetric', 'minsize', 'maxsize', 'linethickness', 'scriptlevel',
      'displaystyle', 'depth', 'voffset', 'notation', 'rowalign', 'form', 'mathsize',
    ],
    /*
     * 주소는 같은 서버(/) · 본문 안 앵커(#) · http(s) 링크만 받아요. javascript: 같은 건 떨어져요.
     * 그림 src는 위 훅이 같은 서버 주소만 남겨요.
     * DOMPurify는 URI-safe로 알려진 속성(alt·class·id·style·title·xmlns …)이
     * 아니면 **모든** 속성 값을 이 정규식으로 검사해서 떨어뜨려요.
     * 그래서 주소가 아닌 구조 속성은 아래 ADD_URI_SAFE_ATTR로 빼 둬야 해요.
     */
    ALLOWED_URI_REGEXP: /^(?:\/|#|https?:)/,
    ADD_URI_SAFE_ATTR: [
      'colspan', 'rowspan', 'scope', 'width', 'height', 'loading', 'target', 'rel', 'type',
      // MathML
      'display', 'mathvariant', 'encoding', 'columnalign', 'rowspacing', 'columnspacing',
      'alttext', 'stretchy', 'fence', 'separator', 'lspace', 'rspace', 'accent', 'accentunder',
      'largeop', 'movablelimits', 'symmetric', 'minsize', 'maxsize', 'linethickness', 'scriptlevel',
      'displaystyle', 'depth', 'voffset', 'notation', 'rowalign', 'form', 'mathsize',
    ],
    ADD_ATTR: ['data-section', 'data-explain', 'data-cite'],
    /*
     * USE_PROFILES는 위에서 쓴 ALLOWED_TAGS·ALLOWED_ATTR를 통째로 덮어써요
     * (DOMPurify _parseConfig). 좁은 허용 목록을 쓰려면 넣지 않아야 해요.
     * MathML 네임스페이스는 프로필과 무관하게 math* 태그에 허용돼요.
     */
  })
}
