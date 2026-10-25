import { useId, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import type { BiomarkerCandidate, KmDataPoint, SurvivalCurveData } from '@/services/api'

interface KaplanMeierPlotProps {
  title?: string
  candidate?: BiomarkerCandidate
  curve?: SurvivalCurveData
  kmPoints?: KmDataPoint[]
  timeUnit?: string
  className?: string
}

interface StepPoint {
  time: number
  prob: number
  ciLower: number | null
  ciUpper: number | null
  atRisk: number
}

function buildStepPoints(
  rawPoints: KmDataPoint[] | undefined,
  group: 'altered' | 'unaltered',
  fallbackCurve?: SurvivalCurveData,
): StepPoint[] {
  // If discrete kmPoints are supplied
  if (rawPoints && rawPoints.length > 0) {
    const filtered = rawPoints
      .filter((p) => p.group === group)
      .sort((a, b) => a.time - b.time)

    if (filtered.length > 0) {
      return filtered.map((p) => ({
        time: p.time,
        prob: p.survival_probability,
        ciLower: p.ci_lower ?? null,
        ciUpper: p.ci_upper ?? null,
        atRisk: p.at_risk ?? 0,
      }))
    }
  }

  // Fallback to curve data structure
  const est = group === 'altered' ? fallbackCurve?.altered : fallbackCurve?.unaltered
  if (est && est.timeline && est.survival_probability) {
    return est.timeline.map((t, i) => ({
      time: t,
      prob: est.survival_probability?.[i] ?? 1.0,
      ciLower: est.ci_lower?.[i] ?? null,
      ciUpper: est.ci_upper?.[i] ?? null,
      atRisk: est.at_risk?.[i] ?? 0,
    }))
  }

  return []
}

function generateStepPath(
  points: StepPoint[],
  scaleX: (t: number) => number,
  scaleY: (s: number) => number,
  maxTime: number,
): string {
  if (points.length === 0) return ''

  let d = `M ${scaleX(0)} ${scaleY(1.0)}`

  for (const pt of points) {
    const x = scaleX(pt.time)
    const y = scaleY(pt.prob)
    // Horizontal step to x, then vertical drop to y
    d += ` H ${x.toFixed(1)} V ${y.toFixed(1)}`
  }

  // Extend line horizontally to maxTime
  d += ` H ${scaleX(maxTime).toFixed(1)}`
  return d
}

function generateCiBandPath(
  points: StepPoint[],
  scaleX: (t: number) => number,
  scaleY: (s: number) => number,
  maxTime: number,
): string | null {
  const valid = points.filter((p) => p.ciLower !== null && p.ciUpper !== null)
  if (valid.length === 0) return null

  // Forward upper bound steps
  let topPath = `M ${scaleX(0)} ${scaleY(1.0)}`
  for (const pt of valid) {
    const x = scaleX(pt.time)
    const y = scaleY(Math.min(1.0, pt.ciUpper!))
    topPath += ` H ${x.toFixed(1)} V ${y.toFixed(1)}`
  }
  topPath += ` H ${scaleX(maxTime).toFixed(1)}`

  // Backward lower bound steps
  let bottomPath = ''
  for (let i = valid.length - 1; i >= 0; i--) {
    const pt = valid[i]
    const x = scaleX(pt.time)
    const y = scaleY(Math.max(0.0, pt.ciLower!))
    bottomPath += ` H ${x.toFixed(1)} V ${y.toFixed(1)}`
  }
  bottomPath += ` H ${scaleX(0).toFixed(1)} Z`

  return `${topPath} ${bottomPath}`
}

function getInterpolatedPoint(points: StepPoint[], t: number): StepPoint | null {
  if (points.length === 0) return null
  if (t <= 0) return { time: 0, prob: 1.0, ciLower: 1.0, ciUpper: 1.0, atRisk: points[0]?.atRisk ?? 0 }

  let active: StepPoint = {
    time: 0,
    prob: 1.0,
    ciLower: 1.0,
    ciUpper: 1.0,
    atRisk: points[0]?.atRisk ?? 0,
  }
  for (const pt of points) {
    if (pt.time <= t) {
      active = pt
    } else {
      break
    }
  }
  return active
}

export function KaplanMeierPlot({
  title,
  candidate,
  curve,
  kmPoints,
  timeUnit = 'months',
  className,
}: KaplanMeierPlotProps) {
  const headingId = useId()
  const [hoverX, setHoverX] = useState<number | null>(null)

  const altered = useMemo(() => buildStepPoints(kmPoints, 'altered', curve), [kmPoints, curve])
  const unaltered = useMemo(() => buildStepPoints(kmPoints, 'unaltered', curve), [kmPoints, curve])

  const maxTime = useMemo(() => {
    let max = 12
    for (const pt of altered) if (pt.time > max) max = pt.time
    for (const pt of unaltered) if (pt.time > max) max = pt.time
    return Math.ceil(max / 6) * 6 || 24
  }, [altered, unaltered])

  // Canvas bounds
  const width = 600
  const height = 300
  const padLeft = 52
  const padRight = 24
  const padTop = 20
  const padBottom = 40
  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom

  const scaleX = (t: number) => padLeft + Math.min(plotWidth, Math.max(0, (t / maxTime) * plotWidth))
  const scaleY = (s: number) => padTop + (1.0 - Math.min(1.0, Math.max(0, s))) * plotHeight

  const xTicks = useMemo(() => {
    const step = maxTime <= 24 ? 6 : maxTime <= 48 ? 12 : 18
    const ticks: number[] = []
    for (let t = 0; t <= maxTime; t += step) ticks.push(t)
    return ticks
  }, [maxTime])

  const yTicks = [0, 0.25, 0.5, 0.75, 1.0]

  const alteredPath = useMemo(() => generateStepPath(altered, scaleX, scaleY, maxTime), [altered, maxTime])
  const unalteredPath = useMemo(() => generateStepPath(unaltered, scaleX, scaleY, maxTime), [unaltered, maxTime])
  const alteredCi = useMemo(() => generateCiBandPath(altered, scaleX, scaleY, maxTime), [altered, maxTime])
  const unalteredCi = useMemo(() => generateCiBandPath(unaltered, scaleX, scaleY, maxTime), [unaltered, maxTime])

  // Hover calculations
  const hoverTime = hoverX !== null ? Math.max(0, Math.min(maxTime, ((hoverX - padLeft) / plotWidth) * maxTime)) : null
  const hoverAltered = hoverTime !== null ? getInterpolatedPoint(altered, hoverTime) : null
  const hoverUnaltered = hoverTime !== null ? getInterpolatedPoint(unaltered, hoverTime) : null

  const logRankP = curve?.log_rank?.p_value ?? candidate?.p_value
  const hazardRatio = curve?.hazard_ratio ?? candidate?.hazard_ratio
  const deltaOs = candidate?.delta_os_months

  const hasData = altered.length > 0 || unaltered.length > 0

  if (!hasData) {
    return (
      <div className={cn('rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground', className)}>
        No Kaplan-Meier coordinates available for this comparison.
      </div>
    )
  }

  return (
    <figure className={cn('space-y-4', className)} aria-labelledby={headingId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 id={headingId} className="text-base font-semibold text-foreground">
            {title || (candidate?.biomarker ? `${candidate.biomarker} (${candidate.alteration_type || 'Altered'})` : 'Kaplan-Meier Survival Curve')}
          </h4>
          {candidate?.drug && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Stratified by overall survival on <span className="font-medium text-foreground">{candidate.drug}</span>
            </p>
          )}
        </div>

        {/* Statistical Badges */}
        <div className="flex flex-wrap items-center gap-2">
          {logRankP !== undefined && (
            <span
              className={cn(
                'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums',
                logRankP < 0.05
                  ? 'border border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                  : 'border border-border bg-muted text-muted-foreground',
              )}
            >
              Log-rank p = {logRankP < 0.001 ? '< 0.001' : logRankP.toFixed(3)}
            </span>
          )}
          {hazardRatio !== undefined && (
            <span className="inline-flex items-center rounded-md border border-border bg-secondary px-2 py-0.5 text-xs font-medium tabular-nums text-foreground">
              HR = {hazardRatio.toFixed(2)}
            </span>
          )}
          {deltaOs !== undefined && (
            <span className="inline-flex items-center rounded-md border border-border bg-secondary px-2 py-0.5 text-xs font-medium tabular-nums text-foreground">
              Δ OS {deltaOs > 0 ? `+${deltaOs.toFixed(1)}` : deltaOs.toFixed(1)} {timeUnit}
            </span>
          )}
        </div>
      </div>

      {/* SVG Plot Container */}
      <div className="relative overflow-hidden rounded-xl border border-border bg-card p-3 shadow-sm sm:p-4">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full select-none"
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const x = ((e.clientX - rect.left) / rect.width) * width
            if (x >= padLeft && x <= width - padRight) {
              setHoverX(x)
            } else {
              setHoverX(null)
            }
          }}
          onMouseLeave={() => setHoverX(null)}
        >
          {/* Y-axis Gridlines & Labels */}
          {yTicks.map((tick) => {
            const y = scaleY(tick)
            return (
              <g key={tick}>
                <line
                  x1={padLeft}
                  y1={y}
                  x2={width - padRight}
                  y2={y}
                  className={tick === 0 ? 'stroke-border' : 'stroke-border/50'}
                  strokeDasharray={tick === 0 ? undefined : '2,2'}
                />
                <text
                  x={padLeft - 8}
                  y={y + 4}
                  textAnchor="end"
                  className="fill-muted-foreground text-[10px] font-medium tabular-nums"
                >
                  {Math.round(tick * 100)}%
                </text>
              </g>
            )
          })}

          {/* X-axis Gridlines & Labels */}
          {xTicks.map((tick) => {
            const x = scaleX(tick)
            return (
              <g key={tick}>
                <line
                  x1={x}
                  y1={padTop}
                  x2={x}
                  y2={height - padBottom}
                  className="stroke-border/40"
                  strokeDasharray="2,2"
                />
                <text
                  x={x}
                  y={height - padBottom + 16}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px] font-medium tabular-nums"
                >
                  {tick}
                </text>
              </g>
            )
          })}

          {/* Axis Labels */}
          <text
            x={padLeft + plotWidth / 2}
            y={height - 8}
            textAnchor="middle"
            className="fill-muted-foreground text-[11px] font-medium"
          >
            Time ({timeUnit})
          </text>
          <text
            transform={`rotate(-90) translate(${-(padTop + plotHeight / 2)}, 14)`}
            textAnchor="middle"
            className="fill-muted-foreground text-[11px] font-medium"
          >
            Survival Probability
          </text>

          {/* Confidence Interval Shaded Bands */}
          {unalteredCi && (
            <path d={unalteredCi} className="fill-muted-foreground/10 opacity-70" />
          )}
          {alteredCi && (
            <path d={alteredCi} className="fill-brand/15 opacity-80" />
          )}

          {/* Step Curves */}
          {unalteredPath && (
            <path
              d={unalteredPath}
              fill="none"
              className="stroke-muted-foreground"
              strokeWidth="2.25"
              strokeDasharray="5,3"
            />
          )}
          {alteredPath && (
            <path
              d={alteredPath}
              fill="none"
              className="stroke-brand"
              strokeWidth="2.5"
            />
          )}

          {/* Hover crosshair & points */}
          {hoverX !== null && hoverTime !== null && (
            <g>
              <line
                x1={hoverX}
                y1={padTop}
                x2={hoverX}
                y2={height - padBottom}
                className="stroke-foreground/40"
                strokeWidth="1.5"
                strokeDasharray="3,3"
              />
              {hoverAltered && (
                <circle
                  cx={hoverX}
                  cy={scaleY(hoverAltered.prob)}
                  r="4"
                  className="fill-brand stroke-card"
                  strokeWidth="2"
                />
              )}
              {hoverUnaltered && (
                <circle
                  cx={hoverX}
                  cy={scaleY(hoverUnaltered.prob)}
                  r="4"
                  className="fill-muted-foreground stroke-card"
                  strokeWidth="2"
                />
              )}
            </g>
          )}
        </svg>

        {/* Hover Tooltip Overlay */}
        {hoverX !== null && hoverTime !== null && (
          <div
            className="pointer-events-none absolute top-4 z-10 rounded-lg border border-border bg-popover/95 p-2.5 text-xs shadow-md backdrop-blur-sm"
            style={{
              left: `${Math.min(75, Math.max(15, (hoverX / width) * 100))}%`,
              transform: 'translateX(-50%)',
            }}
          >
            <p className="font-semibold text-foreground">
              Month {hoverTime.toFixed(1)} {timeUnit}
            </p>
            <div className="mt-1.5 space-y-1">
              {hoverAltered && (
                <div className="flex items-center gap-2 text-brand">
                  <span className="size-2 rounded-full bg-brand" />
                  <span>Altered:</span>
                  <span className="font-semibold tabular-nums">
                    {(hoverAltered.prob * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    ({hoverAltered.atRisk} at risk)
                  </span>
                </div>
              )}
              {hoverUnaltered && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span className="size-2 rounded-full bg-muted-foreground" />
                  <span>Unaltered:</span>
                  <span className="font-semibold tabular-nums text-foreground">
                    {(hoverUnaltered.prob * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    ({hoverUnaltered.atRisk} at risk)
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Legend & At-Risk Summary Table */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-3">
          <div className="flex flex-wrap items-center gap-6 text-xs">
            <div className="flex items-center gap-2">
              <span className="h-0.5 w-4 rounded-full bg-brand" />
              <span className="font-medium text-foreground">
                {candidate?.biomarker || 'Altered cohort'}
              </span>
              {candidate?.cohort_sizes?.altered !== undefined && (
                <span className="text-muted-foreground">
                  (n = {candidate.cohort_sizes.altered})
                </span>
              )}
              {candidate?.median_surv_altered !== undefined && (
                <span className="rounded bg-brand/10 px-1.5 py-0.5 text-brand">
                  Median: {candidate.median_surv_altered.toFixed(1)} {timeUnit}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className="h-0.5 w-4 rounded-full border-t border-dashed border-muted-foreground" />
              <span className="font-medium text-muted-foreground">Wildtype / Unaltered</span>
              {candidate?.cohort_sizes?.unaltered !== undefined && (
                <span className="text-muted-foreground">
                  (n = {candidate.cohort_sizes.unaltered})
                </span>
              )}
              {candidate?.median_surv_unaltered !== undefined && (
                <span className="rounded bg-muted px-1.5 py-0.5 text-foreground">
                  Median: {candidate.median_surv_unaltered.toFixed(1)} {timeUnit}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* At Risk Numbers Table */}
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-4 font-normal">Months</th>
                {xTicks.map((t) => (
                  <th key={t} className="px-2 py-1 text-center font-normal tabular-nums">
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50 text-[11px]">
              <tr>
                <th className="py-1.5 pr-4 font-medium text-brand">Altered (at risk)</th>
                {xTicks.map((t) => {
                  const pt = getInterpolatedPoint(altered, t)
                  return (
                    <td key={t} className="px-2 py-1.5 text-center tabular-nums text-foreground">
                      {pt?.atRisk ?? '–'}
                    </td>
                  )
                })}
              </tr>
              <tr>
                <th className="py-1.5 pr-4 font-medium text-muted-foreground">Unaltered (at risk)</th>
                {xTicks.map((t) => {
                  const pt = getInterpolatedPoint(unaltered, t)
                  return (
                    <td key={t} className="px-2 py-1.5 text-center tabular-nums text-muted-foreground">
                      {pt?.atRisk ?? '–'}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </figure>
  )
}
