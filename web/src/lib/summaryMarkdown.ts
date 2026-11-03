import type { PaperSummary } from '@/api/types'

/**
 * 요약을 Obsidian 호환 MD로 만들어요 (docs/spec.md I-4).
 * 원문 위치는 HTML이면 `[[파일.html#S3|§3]]`, PDF면 `[[파일.pdf#page=4]] · p.4, §3`.
 */
function cite(summary: PaperSummary, section: number): string {
  return summary.html
    ? ` ([[${summary.file}#S${section}|§${section}]])`
    : ` ([[${summary.file}#page=[쪽]]] · p.[쪽], §${section})`
}

export function buildSummaryMarkdown(summary: PaperSummary): string {
  const out: string[] = [
    '---',
    `title: "${summary.title}"`,
    `authors: ${summary.authors}`,
    `venue: ${summary.venue}`,
  ]

  for (const f of summary.fields) {
    out.push(`${f.label.toLowerCase().replace(/ /g, '_')}: ${f.value}`)
  }

  out.push(`source: ${summary.html ? 'arxiv_html' : 'pdf'}`, '---', '', '## 3줄 요약')
  summary.lines.forEach((l, i) => out.push(`${i + 1}. ${l.text}${cite(summary, i + 3)}`))

  out.push(
    '',
    '## Method',
    summary.method + cite(summary, 4),
    '',
    '## Result',
    summary.result + cite(summary, 5),
    '',
    '## Limitation',
    summary.limitation,
  )

  return out.join('\n')
}
