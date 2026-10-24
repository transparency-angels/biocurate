import type { DataPoint } from '@/types/research'

/** Summary figures computed from the rows, so the summary can never disagree with the table. */
export function summarise(points: DataPoint[]) {
  const values = points.map((point) => point.value)
  const total = values.reduce((sum, value) => sum + value, 0)
  return {
    count: points.length,
    groups: [...new Set(points.map((point) => point.group))],
    mean: points.length > 0 ? total / points.length : null,
    min: points.length > 0 ? Math.min(...values) : null,
    max: points.length > 0 ? Math.max(...values) : null,
  }
}

/** Round axis ticks from zero, with the top tick always above the largest value. */
export function axisTicks(max: number, targetCount = 4) {
  if (max <= 0) return [0, 1]
  const rough = max / targetCount
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude
  let top = Math.ceil(max / step) * step
  if (top === max) top += step
  const ticks: number[] = []
  for (let tick = 0; tick <= top + step / 2; tick += step) ticks.push(Number(tick.toFixed(6)))
  return ticks
}

export const formatValue = (value: number) =>
  value.toLocaleString('en', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
