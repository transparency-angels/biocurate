import { axisTicks, formatValue } from '@/features/research/dataStats'
import { cn } from '@/lib/utils'
import type { DataPoint } from '@/types/research'

// The first group stays neutral, the second carries the brand hue
const GROUP_TONES = ['bg-muted-foreground/55', 'bg-brand']

interface SampleBarChartProps {
  points: DataPoint[]
  groups: string[]
  metric: string
  unit: string
}

/**
 * A small column chart drawn with plain elements, so it needs no chart library.
 * The visual is hidden from assistive technology; the table beside it carries the
 * exact values, and the figure's label summarises the chart.
 */
export function SampleBarChart({ points, groups, metric, unit }: SampleBarChartProps) {
  const max = Math.max(...points.map((point) => point.value))
  const ticks = axisTicks(max)
  const top = ticks[ticks.length - 1]
  const toneFor = (group: string) => GROUP_TONES[groups.indexOf(group) % GROUP_TONES.length]

  return (
    <figure
      role="img"
      aria-label={`Column chart of demo ${metric.toLowerCase()} for ${points.length} samples in ${groups.length} groups. Exact values are in the table below.`}
    >
      <ul aria-hidden="true" className="mb-4 flex flex-wrap gap-x-4 gap-y-1">
        {groups.map((group) => (
          <li key={group} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className={cn('size-2 rounded-[2px]', toneFor(group))} />
            {group}
          </li>
        ))}
      </ul>

      <div aria-hidden="true" className="flex gap-2">
        <div className="relative h-44 w-9 shrink-0">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="absolute right-0 translate-y-1/2 text-[0.6875rem] leading-none text-faint tabular-nums"
              style={{ bottom: `${(tick / top) * 100}%` }}
            >
              {tick}
            </span>
          ))}
        </div>

        <div className="min-w-0 flex-1">
          <div className="relative h-44">
            {ticks.map((tick) => (
              <span
                key={tick}
                className={cn(
                  'absolute inset-x-0 border-t',
                  tick === 0 ? 'border-muted-foreground/50' : 'border-border/70',
                )}
                style={{ bottom: `${(tick / top) * 100}%` }}
              />
            ))}
            <div className="absolute inset-0 flex items-end justify-around gap-1.5 px-1 sm:gap-3">
              {points.map((point) => (
                <span
                  key={point.id}
                  title={`${point.label}: ${formatValue(point.value)} ${unit}`}
                  className={cn('w-full max-w-9 rounded-t-[2px]', toneFor(point.group))}
                  style={{ height: `${(point.value / top) * 100}%` }}
                />
              ))}
            </div>
          </div>
          <div className="mt-2 flex justify-around gap-1.5 px-1 sm:gap-3">
            {points.map((point) => (
              <span key={point.id} className="w-full max-w-9 text-center text-[0.6875rem] text-faint">
                {point.label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <figcaption className="mt-3 text-xs text-faint">
        {metric} ({unit}), illustrative values only.
      </figcaption>
    </figure>
  )
}
