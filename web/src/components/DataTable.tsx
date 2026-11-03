import clsx from 'clsx'
import type { ReactNode } from 'react'
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
  render: (row: R) => ReactNode
}

interface Props<R> {
  label: string
  columns: Column<R>[]
  rows: R[]
  rowKey: (row: R) => string
  /** 본문 셀 여백. 목업마다 13 / 12 / 10px로 달라요 */
  density?: 'cozy' | 'roomy' | 'compact'
  minWidth?: number
  /** 실행 중인 행처럼 배경을 살짝 넣을 때 */
  rowTinted?: (row: R) => boolean
}

/**
 * 목업 4곳에 같은 규칙으로 나오는 표.
 * thead에만 세로 경계선이 있고, 첫/마지막 열은 바깥 여백을 지워 본문
 * 좌우 기준선에 맞춰요.
 */
export function DataTable<R>({
  label,
  columns,
  rows,
  rowKey,
  density = 'cozy',
  minWidth = 760,
  rowTinted,
}: Props<R>) {
  return (
    <div className={s.scroll}>
      <table aria-label={label} style={{ minWidth }} className={clsx(s.table, s[density])}>
        <thead>
          <tr className={s.head}>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={c.width === undefined ? undefined : { width: c.width }}
                className={clsx(s.th, c.align === 'right' && s.right)}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
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
