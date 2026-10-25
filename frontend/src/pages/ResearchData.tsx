import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { FileText, Sparkles, Activity, ArrowRight } from 'lucide-react'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { ScientificText } from '@/components/overview/ScientificText'
import { formatBytes } from '@/features/research/attachments'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import {
  ApiError,
  getAnalysis,
  getAttachments,
  getResearch,
  getSession,
  type AnalysisReport,
  type AttachmentRecord,
  type BiomarkerCandidate,
  type KmDataPoint,
  type SessionSnapshot,
} from '@/services/api'
import type { Hypothesis, ResearchSession } from '@/types/research'
import { KaplanMeierPlot } from '@/components/data/KaplanMeierPlot'
import { cn } from '@/lib/utils'
import { NotFoundPage } from './NotFoundPage'

export function ResearchData() {
  const { sessionId = '' } = useParams()
  const location = useLocation()
  const [analysis, setAnalysis] = useState<AnalysisReport | null>(null)
  const [attachments, setAttachments] = useState<AttachmentRecord[]>([])
  const [researchSession, setResearchSession] = useState<ResearchSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sessionStatus, setSessionStatus] = useState<SessionSnapshot['status'] | null>(null)
  const [selectedCandidateKey, setSelectedCandidateKey] = useState<string | null>(null)

  const refresh = useCallback(() => {
    return Promise.all([
      getSession(sessionId),
      getAttachments(sessionId),
      getAnalysis(sessionId).catch((e: Error) => {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }),
      getResearch(sessionId, true).catch(() => null),
    ])
      .then(([session, attached, report, research]) => {
        setSessionStatus(session.status)
        setAnalysis(report)
        setAttachments(attached.attachments)
        setResearchSession(research)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  useEffect(() => {
    let active = true
    const load = () => {
      if (active) void refresh()
    }
    load()
    const timer =
      sessionStatus === null || sessionStatus === 'running'
        ? window.setInterval(load, 4000)
        : undefined
    return () => {
      active = false
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [refresh, sessionStatus])

  useDocumentTitle('Dataset analysis')

  // Pick requested candidate or hypothesis from URL query params
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const reqCandidate = params.get('candidate')
    const reqHypothesis = params.get('hypothesis')

    if (reqCandidate) {
      setSelectedCandidateKey(reqCandidate)
    } else if (reqHypothesis && researchSession?.hypotheses) {
      const foundHyp = researchSession.hypotheses.find((h) => h.id === reqHypothesis)
      if (foundHyp?.candidateKey) {
        setSelectedCandidateKey(foundHyp.candidateKey)
      }
    }
  }, [location.search, researchSession])

  const candidates: BiomarkerCandidate[] = useMemo(() => {
    return analysis?.candidates ?? []
  }, [analysis])

  const activeCandidate = useMemo(() => {
    if (!candidates || candidates.length === 0) return null
    if (selectedCandidateKey) {
      const found = candidates.find((c) => c.candidate_key === selectedCandidateKey)
      if (found) return found
    }
    return candidates[0]
  }, [candidates, selectedCandidateKey])

  const activeCurve = useMemo(() => {
    if (!analysis?.survival_curves || !activeCandidate?.candidate_key) return undefined
    return analysis.survival_curves.find(
      (c) => c.association?.candidate_key === activeCandidate.candidate_key,
    )
  }, [analysis, activeCandidate])

  const activeKmPoints = useMemo(() => {
    if (!analysis?.points || !activeCandidate?.candidate_key) return undefined
    const kmKey = `${activeCandidate.candidate_key}|km`
    return analysis.points[kmKey]?.points as KmDataPoint[] | undefined
  }, [analysis, activeCandidate])

  // Map candidate keys to linked hypotheses
  const hypothesesByCandidateKey = useMemo(() => {
    const map = new Map<string, Hypothesis[]>()
    if (!researchSession?.hypotheses) return map

    for (const h of researchSession.hypotheses) {
      const candKey =
        h.candidateKey ||
        (h.dataEvidence as { candidate_key?: string } | null | undefined)?.candidate_key

      if (candKey) {
        const list = map.get(candKey) ?? []
        list.push(h)
        map.set(candKey, list)
        continue
      }

      // Check description or biomarker
      const biomarker = (h.dataEvidence as { biomarker?: string } | null | undefined)?.biomarker
      if (biomarker && candidates.length > 0) {
        const match = candidates.find(
          (c) => c.biomarker?.toLowerCase() === biomarker.toLowerCase(),
        )
        if (match?.candidate_key) {
          const list = map.get(match.candidate_key) ?? []
          list.push(h)
          map.set(match.candidate_key, list)
          continue
        }
      }

      const desc = (h.dataSummary?.description || '').toLowerCase()
      for (const c of candidates) {
        if (c.biomarker && desc.includes(c.biomarker.toLowerCase()) && c.candidate_key) {
          const list = map.get(c.candidate_key) ?? []
          list.push(h)
          map.set(c.candidate_key, list)
        }
      }
    }
    return map
  }, [researchSession, candidates])

  const linkedHypothesesForActive = useMemo(() => {
    if (!activeCandidate?.candidate_key) return []
    return hypothesesByCandidateKey.get(activeCandidate.candidate_key) ?? []
  }, [activeCandidate, hypothesesByCandidateKey])

  if (error && sessionStatus === null) {
    return <NotFoundPage title="Dataset analysis unavailable" message={error} />
  }

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />
      <div className="mt-5">
        <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">
          Dataset analysis
        </h1>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Biomarker survival profiling, interactive Kaplan-Meier curves, and empirical cohort breakdowns.
        </p>
      </div>
      {error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Could not refresh just now. Showing the latest saved analysis.
        </p>
      )}

      {attachments.length > 0 && (
        <section
          aria-labelledby="attached-files-title"
          className="mt-6 rounded-xl border border-border bg-card"
        >
          <div className="border-b border-border px-5 py-3.5 sm:px-6">
            <h2 id="attached-files-title" className="text-sm font-semibold text-foreground">
              Attached files
            </h2>
          </div>
          <ul className="divide-y divide-border">
            {attachments.map((file) => (
              <li
                key={file.id}
                className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 sm:px-6"
              >
                <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                  <FileText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{file.filename}</span>
                </span>
                <span className="text-xs text-muted-foreground">
                  {file.kind === 'tabular' ? 'Dataset' : 'Document'} · {formatBytes(file.size)} ·{' '}
                  {file.status}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loading ? (
        <p className="mt-8 text-sm text-muted-foreground">Loading dataset analysis…</p>
      ) : !analysis ? (
        <section className="mt-6 rounded-xl border border-border bg-card px-5 py-6 sm:px-6">
          <h2 className="text-sm font-semibold text-foreground">No dataset analysis available</h2>
          <p className="mt-1.5 max-w-[68ch] text-sm leading-6 text-muted-foreground">
            This session has no completed analysis from tabular data. Attach a CSV or TXT dataset
            when starting a research session to enable biomarker and survival analysis.
          </p>
        </section>
      ) : (
        <div className="mt-6 space-y-8">
          {/* Cohort Overview Metrics */}
          <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-6">
            <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
              {analysis.sample_count !== undefined && (
                <p>
                  <span className="text-muted-foreground">Cohort samples</span>
                  <span className="ml-2 font-medium tabular-nums text-foreground">
                    {analysis.sample_count}
                  </span>
                </p>
              )}
              {analysis.candidates && (
                <p>
                  <span className="text-muted-foreground">Survival comparisons</span>
                  <span className="ml-2 font-medium tabular-nums text-foreground">
                    {analysis.candidates.length}
                  </span>
                </p>
              )}
              {analysis.generated_at && (
                <p>
                  <span className="text-muted-foreground">Profiled</span>
                  <time className="ml-2 text-foreground" dateTime={analysis.generated_at}>
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    }).format(new Date(analysis.generated_at))}
                  </time>
                </p>
              )}
            </div>
          </section>

          {/* Biomarker Survival Curves & Candidates Section */}
          {candidates.length > 0 && (
            <section className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold tracking-tight text-foreground">
                  Biomarker Survival Candidates
                </h2>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Select a candidate comparison to inspect its interactive Kaplan-Meier survival curve and hypothesis linkages.
                </p>
              </div>

              <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:items-start lg:gap-8">
                {/* Candidate Selection List */}
                <div className="space-y-2">
                  {candidates.map((cand) => {
                    const isSelected = activeCandidate?.candidate_key === cand.candidate_key
                    const linkedHyps = cand.candidate_key
                      ? hypothesesByCandidateKey.get(cand.candidate_key) ?? []
                      : []

                    return (
                      <button
                        key={cand.candidate_key || `${cand.biomarker}-${cand.drug}`}
                        type="button"
                        onClick={() => setSelectedCandidateKey(cand.candidate_key || null)}
                        className={cn(
                          'flex w-full flex-col gap-1.5 rounded-xl border p-3.5 text-left transition-colors outline-none',
                          'focus-visible:ring-3 focus-visible:ring-ring/50',
                          isSelected
                            ? 'border-brand/40 bg-brand/[0.045] shadow-sm'
                            : 'border-border/80 bg-card hover:border-input hover:bg-secondary/60',
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-foreground">
                            {cand.biomarker || 'Candidate'}
                          </span>
                          <span
                            className={cn(
                              'inline-flex items-center rounded px-1.5 py-0.5 text-[0.6875rem] font-medium tabular-nums',
                              (cand.p_value ?? 1) < 0.05
                                ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                                : 'bg-muted text-muted-foreground',
                            )}
                          >
                            p = {(cand.p_value ?? 0) < 0.001 ? '<0.001' : (cand.p_value ?? 0).toFixed(3)}
                          </span>
                        </div>

                        <div className="text-xs text-muted-foreground">
                          {cand.alteration_type || 'Altered'}
                          {cand.drug && <span> · on {cand.drug}</span>}
                        </div>

                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.6875rem]">
                          {cand.hazard_ratio !== undefined && (
                            <span className="rounded bg-secondary px-1.5 py-0.5 font-medium tabular-nums text-foreground">
                              HR {cand.hazard_ratio.toFixed(2)}
                            </span>
                          )}
                          {linkedHyps.length > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-brand/10 px-1.5 py-0.5 font-medium text-brand">
                              <Sparkles className="size-2.5" />
                              {linkedHyps.length} linked hypothesis
                              {linkedHyps.length === 1 ? '' : 'es'}
                            </span>
                          )}
                        </div>
                      </button>
                    )
                  })}
                </div>

                {/* Active Candidate Detailed View & Interactive Kaplan-Meier Curve */}
                <div className="space-y-6">
                  {activeCandidate && (
                    <div className="rounded-2xl border border-border bg-card p-5 sm:p-6 shadow-sm">
                      <KaplanMeierPlot
                        candidate={activeCandidate}
                        curve={activeCurve}
                        kmPoints={activeKmPoints}
                        timeUnit="months"
                        title={`${activeCandidate.biomarker || 'Biomarker'} Overall Survival Curve`}
                      />

                      {/* Linked Hypotheses */}
                      {linkedHypothesesForActive.length > 0 && (
                        <div className="mt-6 border-t border-border pt-5">
                          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Hypotheses Grounded in this Biomarker
                          </h4>
                          <div className="mt-3 space-y-2">
                            {linkedHypothesesForActive.map((h) => (
                              <div
                                key={h.id}
                                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/80 bg-background/60 p-3.5"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="flex size-5 items-center justify-center rounded-full bg-muted text-[10px] font-semibold tabular-nums text-muted-foreground">
                                      #{h.rank}
                                    </span>
                                    <span className="truncate text-sm font-medium text-foreground">
                                      {h.title}
                                    </span>
                                  </div>
                                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                                    {h.summary}
                                  </p>
                                </div>
                                <Link
                                  to={`/research/${sessionId}/results?hypothesis=${encodeURIComponent(h.id)}`}
                                  className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                                >
                                  View evaluation
                                  <ArrowRight className="size-3" />
                                </Link>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          {/* Scientific Summary */}
          {analysis.summary_markdown && (
            <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-6">
              <div className="mb-3 flex items-center gap-2">
                <Activity className="size-4 text-brand" />
                <h3 className="text-sm font-semibold text-foreground">
                  Profiling Summary &amp; Statistical Methods
                </h3>
              </div>
              <ScientificText>{analysis.summary_markdown}</ScientificText>
            </section>
          )}

          {/* Static Supplementary Plots */}
          {analysis.plots && analysis.plots.length > 0 && (
            <section className="space-y-4">
              <h2 className="text-base font-semibold text-foreground">
                Supplementary Analysis Figures
              </h2>
              <div className="grid gap-4 lg:grid-cols-2">
                {analysis.plots.map((plot) => (
                  <figure
                    key={plot.name}
                    className="overflow-hidden rounded-xl border border-border bg-card p-3"
                  >
                    <img
                      src={plot.url}
                      alt={`Dataset analysis plot: ${plot.name.replaceAll('_', ' ')}`}
                      loading="lazy"
                      className="h-auto w-full"
                    />
                    <figcaption className="px-2 pt-2 text-sm text-muted-foreground">
                      {plot.name.replaceAll('_', ' ')}
                    </figcaption>
                  </figure>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
