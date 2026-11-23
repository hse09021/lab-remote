import type { CSSProperties, ReactNode } from 'react'
import type { PtRect } from '@/api/types'

/**
 * PDF 렌더러 계약.
 *
 * 지금은 미리 뽑아 둔 쪽 이미지를 쓰는 ImagePdfRenderer 가 들어가고,
 * 3단계에서 pdfjs-dist로 바꿔요. 바뀌는 건 그림을 그리는 방법뿐이고,
 * 좌표는 양쪽 다 PDF pt(612×792) 공간을 써서 오버레이 코드는 그대로예요.
 */

export interface PdfSource {
  pageCount: number
  /** pt 단위 쪽 크기 */
  pageSize: (page: number) => { width: number; height: number }
  /** 쪽 이미지 주소. pdfjs로 바꾸면 안 써요 */
  pageImageUrl?: (page: number) => string
}

export interface PdfPageContext {
  page: number
  /** pt 사각형 [x0,y0,x1,y1] → 쪽 안의 % 위치. 렌더러가 바뀌어도 이 계약은 유지돼요 */
  rectToStyle: (box: PtRect) => CSSProperties
  /** pt 좌표 한 점 → 쪽 안의 % 위치 (버튼을 얹을 때) */
  pointToStyle: (x: number, y: number) => CSSProperties
  /** 텍스트 레이어 선택 → pt 좌표. 이미지 렌더러는 없어서 null */
  getSelectionRects: () => PtRect[] | null
}

export interface PdfRendererProps {
  source: PdfSource
  /** 100% 기준 쪽 너비(px) */
  baseWidth: number
  zoom: number
  /** 쪽마다 겹쳐 그릴 것 */
  children: (ctx: PdfPageContext) => ReactNode
  /** 쪽 요소를 부모에게 알려 줘요 (스크롤 추적용) */
  onPageElement?: (page: number, el: HTMLElement | null) => void
}
