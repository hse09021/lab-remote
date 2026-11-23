/**
 * 지식그래프 노드 배치 — Fruchterman-Reingold 힘 배치를 **결정적으로** 돌려요.
 * 같은 그래프면 언제 열어도 같은 자리에 나와요(난수 없음).
 */
export interface Point {
  x: number
  y: number
}

export interface LayoutBox {
  width: number
  height: number
  /** 위·아래·왼쪽 여백 */
  pad: number
  /** 오른쪽 여백 — 노드 이름이 점 오른쪽에 붙어서 더 둬요 */
  padRight: number
}

export function layoutGraph(ids: string[], edges: Array<[string, string]>, box: LayoutBox): Record<string, Point> {
  const n = ids.length
  const out: Record<string, Point> = {}
  if (n === 0) return out
  const index = new Map(ids.map((id, i) => [id, i]))
  const links = edges
    .map(([a, b]) => [index.get(a), index.get(b)] as const)
    .filter((e): e is readonly [number, number] => e[0] !== undefined && e[1] !== undefined && e[0] !== e[1])

  // 처음 자리: 해바라기 나선 (골고루 퍼지고 겹치지 않아요)
  const W = 1000
  const H = 800
  const xs = new Float64Array(n)
  const ys = new Float64Array(n)
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const r = Math.sqrt((i + 0.5) / n) * (Math.min(W, H) / 2.2)
    xs[i] = W / 2 + r * Math.cos(i * golden)
    ys[i] = H / 2 + r * Math.sin(i * golden)
  }

  const k = Math.sqrt((W * H) / n) * 0.75
  const iterations = n > 200 ? 120 : 300
  let temp = W / 8
  const cool = temp / iterations
  const dx = new Float64Array(n)
  const dy = new Float64Array(n)

  for (let it = 0; it < iterations; it++) {
    dx.fill(0)
    dy.fill(0)
    // 밀어내기
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ddx = xs[i] - xs[j]
        let ddy = ys[i] - ys[j]
        let d2 = ddx * ddx + ddy * ddy
        if (d2 < 0.01) {
          ddx = 0.1 * ((i % 7) - 3)
          ddy = 0.1 * ((j % 5) - 2) || 0.1
          d2 = ddx * ddx + ddy * ddy
        }
        const f = (k * k) / d2
        dx[i] += ddx * f
        dy[i] += ddy * f
        dx[j] -= ddx * f
        dy[j] -= ddy * f
      }
    }
    // 당기기 (이어진 것끼리)
    for (const [a, b] of links) {
      const ddx = xs[a] - xs[b]
      const ddy = ys[a] - ys[b]
      const d = Math.sqrt(ddx * ddx + ddy * ddy) || 0.01
      const f = d / k
      dx[a] -= ddx * f
      dy[a] -= ddy * f
      dx[b] += ddx * f
      dy[b] += ddy * f
    }
    // 가운데로 살짝 (떨어진 무리가 멀리 가지 않게)
    for (let i = 0; i < n; i++) {
      dx[i] += (W / 2 - xs[i]) * 0.02
      dy[i] += (H / 2 - ys[i]) * 0.02
      const len = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1
      const step = Math.min(len, temp)
      xs[i] += (dx[i] / len) * step
      ys[i] += (dy[i] / len) * step
    }
    temp = Math.max(temp - cool, 1)
  }

  // 상자에 맞춰 늘이기
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (let i = 0; i < n; i++) {
    minX = Math.min(minX, xs[i])
    maxX = Math.max(maxX, xs[i])
    minY = Math.min(minY, ys[i])
    maxY = Math.max(maxY, ys[i])
  }
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  const innerW = box.width - box.pad - box.padRight
  const innerH = box.height - box.pad * 2
  for (let i = 0; i < n; i++) {
    out[ids[i]] = {
      x: Math.round(n === 1 ? box.width / 2 : box.pad + ((xs[i] - minX) / spanX) * innerW),
      y: Math.round(n === 1 ? box.height / 2 : box.pad + ((ys[i] - minY) / spanY) * innerH),
    }
  }
  return out
}
