import { useId, type ReactNode } from 'react'
import { Link } from 'react-router'
import { ArrowUpRight, ChartColumn, CircleAlert, CircleCheck, CircleMinus, Download, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatCount, formatP, formatValue, pointsCsv, VERDICT_COPY } from '@/features/research/dataStats'
import { cn } from '@/lib/utils'
import type { DataAnalysis, DataVerdict, Hypothesis } from '@/types/research'
import { SurvivalChart } from './SurvivalChart'

const VERDICT_STYLE: Record<DataVerdict, { icon: typeof CircleCheck; tone: string }> = {
  supported: { icon: CircleCheck, tone: 'border-success/40 bg-success/8 text-success' },
  nominal: { icon: CircleAlert, tone: 'border-amber/40 bg-amber/8 text-amber' },
  not_significant: { icon: CircleMinus, tone: 'border-border bg-muted/40 text-muted-foreground' },
  not_tested: { icon: ChartColumn, tone: 'border-border bg-muted/40 text-muted-foreground' },
}

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="border-t border-border pt-6">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id={headingId} className="text-sm font-semibold text-foreground">{title}</h3>
        {aside}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Verdict({ analysis }: { analysis: DataAnalysis }) {
  const { icon: Icon, tone } = VERDICT_STYLE[analysis.status]
  const copy = VERDICT_COPY[analysis.status]
  return (
    <div className={cn('flex gap-3 rounded-xl border p-4', tone)}>
      <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0">
        <p className="text-sm font-semibold">{copy.label}</p>
        <p className="mt-1 text-sm leading-6 text-foreground">{analysis.headline}</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{copy.meaning}</p>
      </div>
    </div>
  )
}

function Figure({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="bg-card px-4 py-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-lg font-medium text-foreground tabular-nums">{value}</dd>
      {note && <dd className="mt-0.5 text-xs leading-4 text-faint">{note}</dd>}
    </div>
  )
}

function KeyFigures({ analysis }: { analysis: DataAnalysis }) {
  const { effect, significance, groups, endpoint } = analysis
  if (!effect || !significance) return null
  const unit = endpoint?.unit ?? ''
  const altered = groups.find((g) => g.group === 'altered')
  const hr = effect.hazardRatio
  const delta = effect.medianDifference
  return (
    <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      <Figure
        label="Difference in median"
        value={delta === null ? '–' : <>{delta > 0 ? '+' : ''}{formatValue(delta)}<span className="ml-1 text-sm font-normal text-faint">{unit}</span></>}
        note={delta === null ? 'A median was not reached' : `${altered?.label ?? 'Altered'} vs without`}
      />
      <Figure
        label="Hazard ratio (95% CI)"
        value={hr === null ? '–' : <>{hr.toFixed(2)}<span className="ml-1 text-sm font-normal text-faint">{effect.hazardRatioLower?.toFixed(2)}–{effect.hazardRatioUpper?.toFixed(2)}</span></>}
        note={hr === null ? 'Model did not converge' : `${hr >= 1 ? hr.toFixed(1) + '× the' : (1 / hr).toFixed(1) + '× lower'} rate of events`}
      />
      <Figure
        label="Significance"
        value={<>q {formatP(significance.qValue)}</>}
        note={`p ${formatP(significance.pValue)}${significance.testsRun ? ` · FDR across ${formatCount(significance.testsRun)} tests` : ''}`}
      />
      <Figure
        label="Samples (events)"
        value={formatCount(groups.reduce((sum, g) => sum + g.n, 0))}
        note={groups.map((g) => `${g.n}${g.events === null ? '' : ` (${g.events})`}`).join(' vs ')}
      />
    </dl>
  )
}

function GroupTable({ analysis }: { analysis: DataAnalysis }) {
  const unit = analysis.endpoint?.unit ?? ''
  const head = 'h-9 text-xs font-normal text-muted-foreground'
  return (
    <table className="mt-4 w-full text-sm">
      <caption className="sr-only">Group sizes, events and median survival</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className={cn(head, 'text-left')}>Group</th>
          <th scope="col" className={cn(head, 'text-right')}>Samples</th>
          <th scope="col" className={cn(head, 'text-right')}>Events</th>
          <th scope="col" className={cn(head, 'text-right')}>Censored</th>
          <th scope="col" className={cn(head, 'text-right')}>Median ({unit})</th>
        </tr>
      </thead>
      <tbody>
        {analysis.groups.map((g) => (
          <tr key={g.group} className="border-b border-border/60 last:border-0">
            <th scope="row" className="h-10 pr-3 text-left font-medium text-foreground">{g.label}</th>
            <td className="text-right tabular-nums">{g.n}</td>
            <td className="text-right tabular-nums">{g.events ?? '–'}</td>
            <td className="text-right tabular-nums">{g.censored ?? '–'}</td>
            <td className="text-right tabular-nums">{g.median === null ? 'not reached' : formatValue(g.median)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Caveats({ analysis }: { analysis: DataAnalysis }) {
  if (analysis.caveats.length === 0) return null
  return (
    <Section title="Before you rely on this">
      <ul className="space-y-3">
        {analysis.caveats.map((caveat) => {
          const Icon = caveat.level === 'warning' ? CircleAlert : Info
          return (
            <li key={caveat.text} className="flex gap-3">
              <Icon aria-hidden="true" className={cn('mt-0.5 size-4 shrink-0', caveat.level === 'warning' ? 'text-amber' : 'text-muted-foreground')} />
              <div className="min-w-0 text-sm leading-6">
                <p className="text-foreground">{caveat.text}</p>
                <p className="text-muted-foreground"><span className="font-medium">Next check:</span> {caveat.action}</p>
              </div>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

function RelatedFindings({ analysis }: { analysis: DataAnalysis }) {
  if (analysis.relatedFindings.length === 0) return null
  return (
    <Section title="Related findings in your data">
      <ul className="divide-y divide-border/60 rounded-lg border border-border">
        {analysis.relatedFindings.map((finding) => (
          <li key={finding.title} className="px-4 py-3">
            <p className="text-sm font-medium text-foreground">{finding.title}</p>
            {finding.detail && <p className="mt-0.5 text-sm text-muted-foreground">{finding.detail}</p>}
            <p className="mt-1 text-xs text-faint tabular-nums">
              {finding.test} · {finding.effect} · p {formatP(finding.pValue)} · q {formatP(finding.qValue)}
            </p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

function Methods({ analysis }: { analysis: DataAnalysis }) {
  if (analysis.methods.length === 0) return null
  return (
    <details className="group border-t border-border pt-6">
      <summary className="cursor-pointer text-sm font-semibold text-foreground">Methods and reproducibility</summary>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
        {analysis.methods.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="break-words text-foreground">{row.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

function SampleData({ hypothesis }: { hypothesis: Hypothesis }) {
  const { dataPoints, dataSummary } = hypothesis
  if (dataPoints.length === 0) return null
  const unit = dataSummary.unit
  const download = () => {
    const blob = new Blob([pointsCsv(dataPoints, unit)], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${hypothesis.id}-samples.csv`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <details className="border-t border-border pt-6">
      <summary className="cursor-pointer text-sm font-semibold text-foreground">
        Sample-level data <span className="font-normal text-muted-foreground">({formatCount(dataPoints.length)} samples)</span>
      </summary>
      <div className="mt-3 flex justify-end">
        <Button type="button" variant="outline" size="sm" onClick={download}>
          <Download aria-hidden="true" /> Download CSV
        </Button>
      </div>
      <div className="mt-3 max-h-80 overflow-y-auto">
        <table className="w-full table-fixed text-sm">
          <caption className="sr-only">Time and status for each sample</caption>
          <thead className="sticky top-0 bg-background">
            <tr className="border-b border-border">
              <th scope="col" className="h-9 text-left text-xs font-normal text-muted-foreground">Sample</th>
              <th scope="col" className="h-9 text-left text-xs font-normal text-muted-foreground">Group</th>
              <th scope="col" className="h-9 text-right text-xs font-normal text-muted-foreground">Time ({unit})</th>
              <th scope="col" className="h-9 text-right text-xs font-normal text-muted-foreground">Status</th>
            </tr>
          </thead>
          <tbody>
            {dataPoints.map((point) => (
              <tr key={point.id} className="border-b border-border/60 last:border-0">
                <th scope="row" className="h-9 truncate pr-3 text-left font-medium text-foreground" title={point.label}>{point.label}</th>
                <td className="truncate pr-3 text-muted-foreground">{point.group}</td>
                <td className="text-right tabular-nums">{formatValue(point.value)}</td>
                <td className="text-right text-muted-foreground">
                  {point.event === null ? '–' : point.event ? 'Event' : 'Censored'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

export function DataTab({ hypothesis, sessionId }: { hypothesis: Hypothesis; sessionId: string }) {
  const analysis = hypothesis.dataAnalysis
  const datasetLink = (
    <Link to={`/research/${sessionId}/data`} className="inline-flex items-center gap-1 text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
      Full dataset analysis <ArrowUpRight aria-hidden="true" className="size-3.5" />
    </Link>
  )

  return (
    <div className="space-y-6 px-5 py-6 sm:px-8">
      <Verdict analysis={analysis} />

      {analysis.kind === 'survival' && (
        <>
          <KeyFigures analysis={analysis} />
          <Section title={analysis.endpoint?.label ?? 'Survival'} aside={datasetLink}>
            {analysis.curves.length > 0 ? (
              <SurvivalChart
                curves={analysis.curves}
                atRisk={analysis.atRisk}
                unit={analysis.endpoint?.unit ?? ''}
                endpoint={analysis.endpoint?.label ?? 'Survival'}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                Survival curves are not available for this result; it was analysed before event status was stored.
              </p>
            )}
            <GroupTable analysis={analysis} />
          </Section>
        </>
      )}

      <RelatedFindings analysis={analysis} />
      <Caveats analysis={analysis} />
      <Methods analysis={analysis} />
      <SampleData hypothesis={hypothesis} />

      {analysis.kind !== 'survival' && analysis.kind !== 'none' && <div>{datasetLink}</div>}
    </div>
  )
}
