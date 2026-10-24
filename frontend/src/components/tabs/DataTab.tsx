import { useId, type ReactNode } from 'react'
import { DemoNotice } from '@/components/DemoNotice'
import { formatValue, summarise } from '@/features/research/dataStats'
import type { Hypothesis } from '@/types/research'
import { SampleBarChart } from './SampleBarChart'

function Section({ title, children }: { title: string; children: ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="border-t border-border pt-6">
      <h3 id={headingId} className="text-sm font-semibold text-foreground">
        {title}
      </h3>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Unit({ children }: { children: ReactNode }) {
  return <span className="ml-1 text-sm font-normal text-faint">{children}</span>
}

export function DataTab({ hypothesis }: { hypothesis: Hypothesis }) {
  const { dataSummary, dataPoints } = hypothesis
  const stats = summarise(dataPoints)
  const dash = <span className="text-faint">–</span>

  return (
    <div className="space-y-6 px-5 py-6 sm:px-8">
      <DemoNotice>Demonstration data. These values are invented to show the layout and were not measured.</DemoNotice>

      <Section title="Summary">
        <p className="text-sm leading-6 text-muted-foreground">{dataSummary.description}</p>
        <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
          {[
            { label: 'Samples', value: stats.count },
            { label: 'Groups', value: stats.groups.length },
            {
              label: `Mean ${dataSummary.metric.toLowerCase()}`,
              value: stats.mean === null ? dash : <>{formatValue(stats.mean)}<Unit>{dataSummary.unit}</Unit></>,
            },
            {
              label: 'Range',
              value:
                stats.min === null || stats.max === null ? dash : (
                  <>
                    {formatValue(stats.min)}–{formatValue(stats.max)}
                    <Unit>{dataSummary.unit}</Unit>
                  </>
                ),
            },
          ].map(({ label, value }) => (
            <div key={label} className="bg-card px-4 py-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-lg font-medium text-foreground tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title={`${dataSummary.metric} by sample`}>
        <SampleBarChart
          points={dataPoints}
          groups={stats.groups}
          metric={dataSummary.metric}
          unit={dataSummary.unit}
        />
      </Section>

      <Section title="Sample values">
        <table className="w-full text-sm">
          <caption className="sr-only">Demo {dataSummary.metric.toLowerCase()} for each sample</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="h-9 w-20 pr-4 text-left text-xs font-normal text-muted-foreground">
                Sample
              </th>
              <th scope="col" className="h-9 text-left text-xs font-normal text-muted-foreground">
                Group
              </th>
              <th scope="col" className="h-9 text-right text-xs font-normal text-muted-foreground">
                {dataSummary.metric} ({dataSummary.unit})
              </th>
            </tr>
          </thead>
          <tbody>
            {dataPoints.map((point) => (
              <tr key={point.id} className="border-b border-border/60 last:border-0">
                <th scope="row" className="h-10 text-left font-medium text-foreground">
                  {point.label}
                </th>
                <td className="h-10 text-muted-foreground">{point.group}</td>
                <td className="h-10 text-right text-foreground tabular-nums">{formatValue(point.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  )
}
