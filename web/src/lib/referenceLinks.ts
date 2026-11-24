import type { Reference } from '@/api/types'

export interface RefLink {
  label: string
  href: string
}

/**
 * 인용된 자료로 가는 길 — arXiv 번호가 있으면 arXiv, 참고문헌에 DOI · URL이 있으면 원문,
 * 둘 다 없으면 제목으로 찾아요. `primary`는 제목을 눌렀을 때 여는 곳이에요.
 */
export function referenceLinks(r: Pick<Reference, 'title' | 'arxiv'> & { url?: string | null }): { primary: RefLink; all: RefLink[] } {
  const q = encodeURIComponent(r.title)
  const all: RefLink[] = []
  if (r.arxiv) all.push({ label: 'arXiv에서 열기', href: `https://arxiv.org/abs/${r.arxiv}` })
  if (r.url) all.push({ label: r.url.includes('doi.org/') ? 'DOI로 열기' : '원문 열기', href: r.url })
  const search: RefLink[] = [
    { label: 'arXiv에서 찾기', href: `https://arxiv.org/search/?query=${q}&searchtype=title` },
    { label: 'Google Scholar', href: `https://scholar.google.com/scholar?q=${q}` },
    { label: 'Semantic Scholar', href: `https://www.semanticscholar.org/search?q=${q}` },
  ]
  // 바로 열 곳이 있으면 찾기는 arXiv 찾기만 빼고 붙여요 (같은 걸 두 번 보여 주지 않게)
  const links = all.length ? [...all, ...search.slice(1)] : search
  return { primary: links[0]!, all: links }
}
