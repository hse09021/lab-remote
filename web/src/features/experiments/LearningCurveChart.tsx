import type { LearningCurve } from '@/api/types'
import s from './LearningCurveChart.module.css'

/*
 * 목업(AltFocus)의 SVG 기하를 그대로 옮긴 상수예요.
 * 목업은 좌표가 마크업에 박혀 있었지만 여기서는 loss 값만 받아서 계산해요.
 *   x = LEFT + (epoch / totalEpochs) * (RIGHT - LEFT)   → 40 + 10.8 * epoch
 *   y = AXIS_Y - loss * Y_UNIT                          → 160 - 63.65 * loss
 */
const VIEW = { w: 600, h: 186 }
const LEFT = 40
const RIGHT = 580
const AXIS_RIGHT = 590
const AXIS_Y = 160
const MARKER_TOP = 24
const Y_UNIT = 63.65

/** y축 눈금 라벨을 붙일 loss 값 */
const Y_LABELLED = [0, 1, 2]
/** 가로 보조선을 그릴 loss 값 */
const Y_GRID = [0.5, 1, 1.5, 2]

const round = (n: number) => Math.round(n * 10) / 10

interface Props {
  curve: LearningCurve
  /** 모바일은 더 낮게 그려요 (목업 FocusMobile 은 330×110) */
  size?: 'desktop' | 'mobile'
}

export function LearningCurveChart({ curve, size = 'desktop' }: Props) {
  const x = (epoch: number) => round(LEFT + (epoch / curve.totalEpochs) * (RIGHT - LEFT))
  const y = (loss: number) => round(AXIS_Y - loss * Y_UNIT)

  const points = (series: number[]) =>
    curve.epochs.map((e, i) => `${x(e)},${y(series[i] ?? 0)}`).join(' ')

  // x축 눈금은 전체 범위를 5등분한 자리에 둬요 (50 epoch → 0 / 20 / 40)
  const xTicks: number[] = []
  const step = curve.totalEpochs <= 20 ? 5 : 20
  for (let e = 0; e <= curve.totalEpochs; e += step) xTicks.push(e)

  const lastTrain = curve.train.at(-1) ?? 0
  const lastVal = curve.val.at(-1) ?? 0

  return (
    <svg
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      width="100%"
      role="img"
      aria-label={`train loss는 ${lastTrain.toFixed(2)}, val loss는 ${lastVal.toFixed(2)}까지 하락`}
      data-size={size}
      className={s.chart}
    >
      <line x1={LEFT} y1={AXIS_Y} x2={AXIS_RIGHT} y2={AXIS_Y} className={s.axis} />

      {Y_GRID.filter((v) => v <= curve.yMax).map((v) => (
        <line key={v} x1={LEFT} y1={y(v)} x2={AXIS_RIGHT} y2={y(v)} className={s.grid} />
      ))}

      {Y_LABELLED.filter((v) => v <= curve.yMax).map((v) => (
        <text key={v} x={LEFT - 8} y={Math.round(y(v)) + 4} textAnchor="end" className={s.tick}>
          {v === 0 ? '0' : v.toFixed(1)}
        </text>
      ))}

      {xTicks.map((e) => (
        <text key={e} x={x(e)} y={178} textAnchor="middle" className={s.tick}>
          {e}
        </text>
      ))}
      <text x={RIGHT} y={178} textAnchor="middle" className={s.tick}>
        epoch
      </text>

      {/* 지금 돌고 있는 epoch 자리 */}
      <line
        x1={x(curve.currentEpoch)}
        y1={MARKER_TOP}
        x2={x(curve.currentEpoch)}
        y2={AXIS_Y}
        className={s.marker}
      />

      {/* val을 먼저 그려서 train이 위에 오게 해요 (목업과 같은 순서) */}
      <polyline points={points(curve.val)} className={`${s.line} ${s.val}`} />
      <polyline points={points(curve.train)} className={`${s.line} ${s.train}`} />
    </svg>
  )
}

export function CurveLegend({ kind, children }: { kind: 'train' | 'val'; children: string }) {
  return (
    <span className={s.legend}>
      <svg width="20" height="6" aria-hidden="true">
        <line
          x1="0"
          y1="3"
          x2="20"
          y2="3"
          className={kind === 'train' ? s.swatchTrain : s.swatchVal}
        />
      </svg>
      {children}
    </span>
  )
}
