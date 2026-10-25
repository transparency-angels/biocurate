import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowRight, Sparkles } from 'lucide-react'
import { formatValue, summarise } from '@/features/research/dataStats'
import type { Hypothesis } from '@/types/research'
import { getAnalysis, type AnalysisReport, type BiomarkerCandidate, type KmDataPoint, type SurvivalCurveData } from '@/services/api'
import { KaplanMeierPlot } from '@/components/data/KaplanMeierPlot'
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

interface DataTabProps {
  hypothesis: Hypothesis
  sessionId?: string
}

export function DataTab({ hypothesis, sessionId }: DataTabProps) {
  const { sessionId: routeSessionId } = useParams()
  const effectiveSessionId = sessionId || routeSessionId
  const [analysis, setAnalysis] = useState<AnalysisReport | null>(null)

  useEffect(() => {
    if (!effectiveSessionId) return
    let active = true
    getAnalysis(effectiveSessionId)
      .then((rep) => {
        if (active) setAnalysis(rep)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [effectiveSessionId])

  // Resolve matching biomarker candidate from data evidence or text
  const matchedCandidate: BiomarkerCandidate | null = useMemo(() => {
    if (!analysis?.candidates || analysis.candidates.length === 0) return null
    const candKey =
      hypothesis.candidateKey ||
      (hypothesis.dataEvidence as { candidate_key?: string } | null | undefined)?.candidate_key

    if (candKey) {
      const found = analysis.candidates.find((c) => c.candidate_key === candKey)
      if (found) return found
    }

    const biomarker = (hypothesis.dataEvidence as { biomarker?: string } | null | undefined)?.biomarker
    if (biomarker) {
      const found = analysis.candidates.find((c) => c.biomarker?.toLowerCase() === biomarker.toLowerCase())
      if (found) return found
    }

    const desc = (hypothesis.dataSummary?.description || '').toLowerCase()
    for (const c of analysis.candidates) {
      if (c.biomarker && desc.includes(c.biomarker.toLowerCase())) {
        return c
      }
    }
    return null
  }, [analysis, hypothesis])

  // Find matching survival curve data
  const matchedCurve: SurvivalCurveData | null = useMemo(() => {
    if (!analysis?.survival_curves || !matchedCandidate?.candidate_key) return null
    return (
      analysis.survival_curves.find(
        (c) => c.association?.candidate_key === matchedCandidate.candidate_key,
      ) ?? null
    )
  }, [analysis, matchedCandidate])

  // Find discrete KM points
  const matchedKmPoints: KmDataPoint[] | undefined = useMemo(() => {
    if (!matchedCandidate?.candidate_key || !analysis?.points) return undefined
    const kmKey = `${matchedCandidate.candidate_key}|km`
    return analysis.points[kmKey]?.points as KmDataPoint[] | undefined
  }, [analysis, matchedCandidate])

  const { dataSummary, dataPoints } = hypothesis
  const stats = summarise(dataPoints)
  const dash = <span className="text-faint">–</span>

  const hasBiomarkerCurve = !!(matchedCandidate && (matchedCurve || (matchedKmPoints && matchedKmPoints.length > 0)))

  return (
    <div className="space-y-6 px-5 py-6 sm:px-8">
      {/* Dynamic Kaplan-Meier Survival Analysis when candidate is linked */}
      {hasBiomarkerCurve && matchedCandidate && (
        <section aria-label="Biomarker Survival Evidence" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-brand" />
              <span className="text-xs font-semibold uppercase tracking-wider text-brand">
                Empirical Biomarker Evidence
              </span>
            </div>
            {effectiveSessionId && (
              <Link
                to={`/research/${effectiveSessionId}/data?candidate=${encodeURIComponent(matchedCandidate.candidate_key || '')}`}
                className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
              >
                View in Dataset Analysis
                <ArrowRight className="size-3" />
              </Link>
            )}
          </div>

          <KaplanMeierPlot
            candidate={matchedCandidate}
            curve={matchedCurve ?? undefined}
            kmPoints={matchedKmPoints}
            timeUnit="months"
            title={`${matchedCandidate.biomarker || 'Biomarker'} Survival Analysis`}
          />
        </section>
      )}

      {/* When no sample points and no biomarker curve */}
      {dataPoints.length === 0 && !hasBiomarkerCurve && (
        <p className="rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          No sample level analysis is linked to this hypothesis. Session wide analysis, when available, is under Dataset analysis.
        </p>
      )}

      {/* Dataset Summary Metrics */}
      {(dataPoints.length > 0 || dataSummary.description.length > 0) && (
        <Section title="Dataset analysis">
          <p className="text-sm leading-6 text-muted-foreground">{dataSummary.description}</p>
          <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
            {[
              { label: 'Samples', value: stats.count },
              { label: 'Groups', value: stats.groups.length },
              {
                label: `Mean ${dataSummary.metric.toLowerCase()}`,
                value:
                  stats.mean === null ? (
                    dash
                  ) : (
                    <>
                      {formatValue(stats.mean)}
                      <Unit>{dataSummary.unit}</Unit>
                    </>
                  ),
              },
              {
                label: 'Range',
                value:
                  stats.min === null || stats.max === null ? (
                    dash
                  ) : (
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
      )}

      {/* Sample Bar Chart */}
      {dataPoints.length > 0 && (
        <Section title={`${dataSummary.metric} by sample`}>
          <SampleBarChart
            points={dataPoints}
            groups={stats.groups}
            metric={dataSummary.metric}
            unit={dataSummary.unit}
          />
        </Section>
      )}

      {/* Sample Values Table */}
      {dataPoints.length > 0 && (
        <Section title="Sample values">
          <table className="w-full text-sm">
            <caption className="sr-only">{dataSummary.metric.toLowerCase()} for each sample</caption>
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
      )}
    </div>
  )
}
