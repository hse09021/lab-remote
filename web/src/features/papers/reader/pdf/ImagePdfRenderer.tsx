import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { PtRect } from '@/api/types'
import type { PdfRendererProps } from './types'
import s from './ImagePdfRenderer.module.css'

/**
 * 미리 뽑아 둔 쪽 이미지로 PDF를 흉내 내는 렌더러.
 * 개발용 fixtures 를 쓰고, 3단계에서 PdfJsRenderer 로 바뀌어요.
 */
export function ImagePdfRenderer({
  source,
  baseWidth,
  zoom,
  children,
  onPageElement,
}: PdfRendererProps) {
  const width = Math.round(baseWidth * zoom)
  const pages = Array.from({ length: source.pageCount }, (_, i) => i + 1)

  return (
    <div className={s.column}>
      {pages.map((page) => {
        const size = source.pageSize(page)
        const ctx = {
          page,
          rectToStyle: (box: PtRect): CSSProperties => ({
            position: 'absolute',
            left: `${(box[0] / size.width) * 100}%`,
            top: `${(box[1] / size.height) * 100}%`,
            width: `${((box[2] - box[0]) / size.width) * 100}%`,
            height: `${((box[3] - box[1]) / size.height) * 100}%`,
          }),
          pointToStyle: (x: number, y: number): CSSProperties => ({
            position: 'absolute',
            left: `${(x / size.width) * 100}%`,
            top: `${(y / size.height) * 100}%`,
          }),
          // 이미지에는 텍스트 레이어가 없어요. pdfjs 로 바꾸면 실제 선택을 돌려줘요
          getSelectionRects: () => null,
        }

        return (
          <div
            key={page}
            id={`pdf-page-${page}`}
            ref={(el) => onPageElement?.(page, el)}
            style={{ width, aspectRatio: `${size.width} / ${size.height}` }}
            className={s.page}
          >
            <PageImage source={source} page={page} />
            {children(ctx)}
          </div>
        )
      })}
    </div>
  )
}

function PageImage({ source, page }: { source: PdfRendererProps['source']; page: number }) {
  const [failed, setFailed] = useState(false)
  const url = source.pageImageUrl?.(page)

  if (!url || failed) {
    return <div className={s.missing}>{page}쪽 · 개발용 쪽 이미지가 없어요</div>
  }
  return (
    <img
      src={url}
      alt={`PDF ${page}쪽`}
      loading="lazy"
      onError={() => setFailed(true)}
      className={s.image}
    />
  )
}
