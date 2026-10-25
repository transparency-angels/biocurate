import type { AtRiskRow, SurvivalCurve } from '@/types/research'
import { cn } from '@/lib/utils'

// The comparison group carries the brand hue; the reference group stays neutral
const TONES: Record<SurvivalCurve['group'], { line: string; band: string; swatch: string }> = {
  altered: { line: 'stroke-brand', band: 'fill-brand/12', swatch: 'bg-brand' },
  unaltered: { line: 'stroke-muted-foreground', band: 'fill-muted-foreground/12', swatch: 'bg-muted-foreground' },
}

const WIDTH = 640
const PLOT_HEIGHT = 260
const PAD = { top: 12, right: 16, bottom: 30, left: 44 }
// Numbers at risk sit inside the drawing so each count lines up with its time tick
const RISK_HEADER = 22
const RISK_ROW = 32
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1]

interface SurvivalChartProps {
  curves: SurvivalCurve[]
  atRisk: AtRiskRow[]
  unit: string
  endpoint: string
}

/** The value of a step curve at time `t`: the last step at or before it. */
function survivalAt(curve: SurvivalCurve, t: number) {
  let s = 1
  for (const step of curve.steps) {
    if (step.t > t) break
    s = step.s
  }
  return s
}

/**
 * Kaplan-Meier curves with 95% bands, censoring marks and a numbers-at-risk table.
 * The drawing is decorative for assistive technology; the label states the medians,
 * and the group table beside it carries the exact figures.
 */
export function SurvivalChart({ curves, atRisk, unit, endpoint }: SurvivalChartProps) {
  const tMax = Math.max(
    ...curves.flatMap((curve) => [...curve.steps.map((step) => step.t), ...curve.censored]),
    ...atRisk.map((row) => row.t),
    1,
  )
  const innerW = WIDTH - PAD.left - PAD.right
  const innerH = PLOT_HEIGHT - PAD.top - PAD.bottom
  const riskTop = PLOT_HEIGHT + RISK_HEADER
  const height = atRisk.length > 0 ? riskTop + curves.length * RISK_ROW : PLOT_HEIGHT
  const x = (t: number) => PAD.left + (t / tMax) * innerW
  const y = (s: number) => PAD.top + (1 - s) * innerH

  const linePath = (curve: SurvivalCurve) => {
    let d = `M${x(0)},${y(1)}`
    for (const step of curve.steps.slice(1)) d += `H${x(step.t)}V${y(step.s)}`
    return `${d}H${x(tMax)}`
  }

  // Upper bound left to right, then the lower bound back, both as steps
  const bandPath = (curve: SurvivalCurve) => {
    const steps = curve.steps
    let d = `M${x(0)},${y(steps[0].upper)}`
    for (let i = 1; i < steps.length; i++) d += `H${x(steps[i].t)}V${y(steps[i].upper)}`
    d += `H${x(tMax)}V${y(steps[steps.length - 1].lower)}`
    for (let i = steps.length - 1; i >= 1; i--) d += `H${x(steps[i].t)}V${y(steps[i - 1].lower)}`
    return `${d}H${x(0)}Z`
  }

  const label = `Kaplan-Meier curves of ${endpoint.toLowerCase()} for ${curves
    .map((curve) => curve.label)
    .join(' and ')}, over ${Math.round(tMax)} ${unit}. Medians and counts are in the table below.`

  return (
    <figure>
      <ul aria-hidden="true" className="mb-3 flex flex-wrap gap-x-4 gap-y-1">
        {curves.map((curve) => (
          <li key={curve.group} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className={cn('h-0.5 w-4 rounded-full', TONES[curve.group].swatch)} />
            {curve.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="text-sm leading-none">+</span> censored
        </li>
      </ul>

      <svg role="img" aria-label={label} viewBox={`0 0 ${WIDTH} ${height}`} className="h-auto w-full overflow-visible">
        {Y_TICKS.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left} x2={WIDTH - PAD.right} y1={y(tick)} y2={y(tick)}
              className={cn(tick === 0.5 ? 'stroke-border [stroke-dasharray:4_4]' : 'stroke-border/70')}
            />
            <text x={PAD.left - 8} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-faint text-[11px] tabular-nums">
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        {atRisk.map((row) => (
          <text key={row.t} x={x(row.t)} y={PLOT_HEIGHT - PAD.bottom + 16} textAnchor="middle" className="fill-faint text-[11px] tabular-nums">
            {row.t}
          </text>
        ))}
        <text x={PAD.left + innerW / 2} y={PLOT_HEIGHT - 2} textAnchor="middle" className="fill-muted-foreground text-[11px]">
          Time ({unit})
        </text>

        {curves.map((curve) => (
          <path key={`band-${curve.group}`} d={bandPath(curve)} className={TONES[curve.group].band} />
        ))}
        {curves.map((curve) => (
          <path
            key={`line-${curve.group}`} d={linePath(curve)} fill="none" strokeWidth={2}
            className={TONES[curve.group].line}
          />
        ))}
        {curves.map((curve) =>
          curve.censored.map((t, i) => (
            <path
              key={`c-${curve.group}-${i}`}
              d={`M${x(t) - 3.5},${y(survivalAt(curve, t))}h7M${x(t)},${y(survivalAt(curve, t)) - 3.5}v7`}
              strokeWidth={1.25}
              className={TONES[curve.group].line}
            />
          )),
        )}

        {atRisk.length > 0 && (
          <g>
            <text x={0} y={riskTop - 6} className="fill-muted-foreground text-[11px] font-medium">
              Number at risk
            </text>
            {curves.map((curve, i) => (
              <g key={`risk-${curve.group}`}>
                <text x={PAD.left} y={riskTop + i * RISK_ROW + 8} className="fill-faint text-[10px]">
                  {curve.label}
                </text>
                {atRisk.map((row) => (
                  <text
                    key={row.t} x={x(row.t)} y={riskTop + i * RISK_ROW + 22} textAnchor="middle"
                    className="fill-foreground text-[11px] tabular-nums"
                  >
                    {row[curve.group]}
                  </text>
                ))}
              </g>
            ))}
          </g>
        )}
      </svg>
    </figure>
  )
}
