import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'
import { VisuallyHidden } from './VisuallyHidden'
import s from './DataTable.module.css'

export interface Column<R> {
  key: string
  label: string
  align?: 'left' | 'right'
  /**
   * <td>에 직접 붙일 클래스.
   * 글자 크기는 셀에 걸어야 해요 — 안쪽 <span>에 주면 줄 상자 기준선이
   * 셀 기본 크기(14px)로 잡혀서 글자가 몇 px 내려가요.
   */
  cellClassName?: string
  /**
   * 열 너비 힌트. <th>에 걸어요 — <td>에 주면 표 자동 배치가 다르게 계산해요.
   * box-sizing:border-box 기준이라 패딩·테두리를 포함한 값이에요.
   * (목업은 box-sizing 리셋이 없어서 같은 숫자가 내용 너비였어요)
   */
  width?: number | string
  /** 헤더 글자를 스크린 리더에게만 보여 줘요 (체크박스 열 등) */
  headerHidden?: boolean
  render: (row: R) => ReactNode
}

interface Props<R> {
  label: string
  columns: Column<R>[]
  rows: R[]
  rowKey: (row: R) => string
  /** 본문 셀 세로 여백. 목업마다 달라요 (대시보드 13 · 권한 10 · 라이브러리 16/9) */
  cellY?: number
  cellX?: number
  /** 헤더 셀 여백. 목업마다 11 / 12px */
  headY?: number
  headX?: number
  /** 양 끝 열의 바깥 여백을 지워 본문 기준선에 맞출지 */
  flushEdges?: boolean
  minWidth?: number
  /** 실행 중인 행처럼 배경을 살짝 넣을 때 */
  rowTinted?: (row: R) => boolean
  /** 행이 하나도 없을 때 보여 줄 문구 */
  emptyMessage?: string
}

/** 목업 여러 곳에 같은 규칙으로 나오는 표 */
export function DataTable<R>({
  label,
  columns,
  rows,
  rowKey,
  cellY = 13,
  cellX = 12,
  headY = 11,
  headX = 12,
  flushEdges = true,
  minWidth = 760,
  rowTinted,
  emptyMessage,
}: Props<R>) {
  const vars = {
    minWidth,
    '--cell-y': `${cellY}px`,
    '--cell-x': `${cellX}px`,
    '--head-y': `${headY}px`,
    '--head-x': `${headX}px`,
  } as CSSProperties

  return (
    <div className={s.scroll}>
      <table
        aria-label={label}
        style={vars}
        className={clsx(s.table, flushEdges && s.flush)}
      >
        <thead>
          <tr className={s.head}>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={c.width === undefined ? undefined : { width: c.width }}
                className={clsx(s.th, c.align === 'right' && s.right)}
              >
                {c.headerHidden ? <VisuallyHidden>{c.label}</VisuallyHidden> : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && emptyMessage && (
            <tr>
              <td colSpan={columns.length} className={clsx(s.td, s.empty)}>
                {emptyMessage}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={rowKey(row)} className={clsx(rowTinted?.(row) && s.tinted)}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(s.td, c.align === 'right' && s.right, c.cellClassName)}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
