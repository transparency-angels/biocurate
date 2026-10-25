import { useCallback, useEffect, useId, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { ConvergenceSection } from '@/components/overview/ConvergenceSection'
import { ExecutiveSummary } from '@/components/overview/ExecutiveSummary'
import { LimitationsSection } from '@/components/overview/LimitationsSection'
import { OverviewSection } from '@/components/overview/OverviewSection'
import { ResearchDirectionView } from '@/components/overview/ResearchDirectionView'
import { ResearchSources } from '@/components/overview/ResearchSources'
import { sourceElementId } from '@/components/overview/sourceAnchor'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { HypothesisList } from '@/components/HypothesisList'
import { HypothesisStateBadge } from '@/components/HypothesisCard'
import { StatusPill } from '@/components/progress/StatusPill'
import { createSseEventSource } from '@/services/researchEventSource'
import {
  getResearch,
  getSession,
  getSynthesis,
  normaliseSynthesis,
  type SessionSnapshot,
} from '@/services/api'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import type { Hypothesis } from '@/types/research'
import type { Citation } from '@/types/researchOverview'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'long' })

function formatGeneratedAt(iso: string | null) {
  if (iso === null) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : dateFormat.format(date)
}

function sortAndRank(items: Hypothesis[]): Hypothesis[] {
  const stateWeight: Record<string, number> = {
    pinned: 4,
    in_tournament: 3,
    reviewed: 2,
    draft: 1,
  }

  const sorted = [...items].sort((a, b) => {
    const eloA = a.elo ?? null
    const eloB = b.elo ?? null
    if (eloA !== null && eloB !== null) {
      if (eloB !== eloA) return eloB - eloA
    } else if (eloA !== null) {
      return -1
    } else if (eloB !== null) {
      return 1
    }

    const weightA = stateWeight[a.state ?? 'draft'] ?? 0
    const weightB = stateWeight[b.state ?? 'draft'] ?? 0
    if (weightA !== weightB) {
      return weightB - weightA
    }

    if (a.createdAt && b.createdAt) {
      const timeDiff = new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      if (timeDiff !== 0) return timeDiff
    }

    return (a.rank || 0) - (b.rank || 0)
  })

  return sorted.map((h, idx) => ({
    ...h,
    rank: idx + 1,
  }))
}

function renderStatusPill(status?: SessionSnapshot['status']) {
  if (!status) return null
  switch (status) {
    case 'running':
      return <StatusPill tone="running">Agents Running</StatusPill>
    case 'done':
      return <StatusPill tone="success">Completed</StatusPill>
    case 'paused':
      return <StatusPill tone="neutral">Paused</StatusPill>
    case 'aborted':
      return <StatusPill tone="neutral">Aborted</StatusPill>
    case 'failed':
      return <StatusPill tone="error">Failed</StatusPill>
    default:
      return null
  }
}

export function ResearchOverview() {
  const { sessionId = '' } = useParams()
  const detailsId = useId()
  const [highlight, setHighlight] = useState<Citation | null>(null)
  const [overview, setOverview] = useState<ReturnType<typeof normaliseSynthesis>>(null)
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [loadingSynthesis, setLoadingSynthesis] = useState(true)
  const [synthesisError, setSynthesisError] = useState<string | null>(null)

  const refreshResearch = useCallback(() => {
    if (!sessionId) return Promise.resolve()
    return getResearch(sessionId, true)
      .then((res) => {
        setHypotheses((prev) => {
          const map = new Map<string, Hypothesis>()
          for (const h of prev) map.set(h.id, h)
          for (const h of res.hypotheses) {
            const existing = map.get(h.id)
            map.set(h.id, existing ? { ...existing, ...h } : h)
          }
          return sortAndRank(Array.from(map.values()))
        })
      })
      .catch(() => undefined)
  }, [sessionId])

  // Initial loads and periodic status poll
  useEffect(() => {
    if (!sessionId) return
    let active = true

    void refreshResearch()
    void getSession(sessionId)
      .then((s) => {
        if (active) setSession(s)
      })
      .catch(() => undefined)

    void getSynthesis(sessionId)
      .then((payload) => {
        if (active) setOverview(normaliseSynthesis(payload))
      })
      .catch((e: Error) => {
        if (active) setSynthesisError(e.message)
      })
      .finally(() => {
        if (active) setLoadingSynthesis(false)
      })

    const timer = window.setInterval(() => {
      void refreshResearch()
      void getSession(sessionId)
        .then((s) => {
          if (active) setSession(s)
        })
        .catch(() => undefined)
    }, 4000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [sessionId, refreshResearch])

  // Real-time SSE streaming for hypothesis generation, reviews, and tournament matches
  useEffect(() => {
    if (!sessionId) return
    const sseSource = createSseEventSource(sessionId)
    const disconnect = sseSource.connect({
      onMessage(msg) {
        try {
          const data = typeof msg.data === 'string' ? JSON.parse(msg.data) : msg.data
          if (!data || typeof data !== 'object') return

          if (msg.event === 'hypothesis_generated') {
            const hid = (data.hypothesis_id as string) || (data.id as string)
            if (!hid) return
            setHypotheses((prev) => {
              const map = new Map(prev.map((h) => [h.id, h]))
              const existing = map.get(hid)
              const updated: Hypothesis = {
                id: hid,
                rank: existing?.rank ?? map.size + 1,
                title: (data.title as string) ?? existing?.title ?? 'Untitled Hypothesis',
                summary: (data.summary as string) ?? existing?.summary ?? '',
                abstract: (data.abstract as string) ?? existing?.abstract ?? '',
                explanation: (data.explanation as string) ?? existing?.explanation ?? '',
                state: (data.state as Hypothesis['state']) ?? 'draft',
                elo: data.elo !== undefined ? (data.elo as number) : existing?.elo ?? null,
                matchesPlayed:
                  (data.matches_played as number) ??
                  (data.matchesPlayed as number) ??
                  existing?.matchesPlayed ??
                  0,
                dataSummary: existing?.dataSummary ?? { description: '', metric: '', unit: '' },
                dataPoints: existing?.dataPoints ?? [],
                sources: existing?.sources ?? [],
              }
              map.set(hid, updated)
              return sortAndRank(Array.from(map.values()))
            })
          } else if (msg.event === 'hypothesis_reviewed') {
            const hid = (data.hypothesis_id as string) || (data.id as string)
            if (!hid) return
            setHypotheses((prev) => {
              const map = new Map(prev.map((h) => [h.id, h]))
              const existing = map.get(hid)
              if (!existing) return prev
              map.set(hid, {
                ...existing,
                state: 'reviewed',
              })
              return sortAndRank(Array.from(map.values()))
            })
          } else if (msg.event === 'match_completed' || msg.event === 'match_complete') {
            const hypA = data.hyp_a as string | undefined
            const hypB = data.hyp_b as string | undefined
            const eloA = data.elo_a_after as number | null | undefined
            const eloB = data.elo_b_after as number | null | undefined
            setHypotheses((prev) => {
              let modified = false
              const map = new Map(prev.map((h) => [h.id, h]))
              if (hypA && map.has(hypA)) {
                const h = map.get(hypA)!
                map.set(hypA, {
                  ...h,
                  state: 'in_tournament',
                  elo: eloA !== undefined && eloA !== null ? eloA : h.elo,
                  matchesPlayed: (h.matchesPlayed ?? 0) + 1,
                })
                modified = true
              }
              if (hypB && map.has(hypB)) {
                const h = map.get(hypB)!
                map.set(hypB, {
                  ...h,
                  state: 'in_tournament',
                  elo: eloB !== undefined && eloB !== null ? eloB : h.elo,
                  matchesPlayed: (h.matchesPlayed ?? 0) + 1,
                })
                modified = true
              }
              if (!modified) return prev
              return sortAndRank(Array.from(map.values()))
            })
          } else if (msg.event === 'session_done' || msg.event === 'final_synthesis_generated') {
            void getSynthesis(sessionId)
              .then((payload) => setOverview(normaliseSynthesis(payload)))
              .catch(() => undefined)
            void getSession(sessionId)
              .then(setSession)
              .catch(() => undefined)
          }
        } catch {
          // Ignore unparseable SSE frame
        }
      },
    })
    return () => {
      disconnect()
    }
  }, [sessionId])

  useDocumentTitle('Research overview')

  // Jumps to the cited source and marks it
  const selectCitation = useCallback((citation: Citation) => {
    const element = document.getElementById(sourceElementId(citation.sourceId))
    if (!element) return
    setHighlight(citation)
    element.focus({ preventScroll: true })
    element.scrollIntoView({ behavior: 'auto', block: 'start' })
  }, [])

  const generatedAt = formatGeneratedAt(overview?.generatedAt ?? null)
  const selectedHypothesis =
    hypotheses.find((h) => h.id === selectedId) ?? hypotheses[0]

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />
      <div className="mt-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">
                Research overview
              </h1>
              {renderStatusPill(session?.status)}
            </div>
          </div>
          {session?.research_goal && (
            <p className="mt-2 max-w-[70ch] text-sm leading-6 text-foreground font-serif italic">
              &ldquo;{session.research_goal}&rdquo;
            </p>
          )}
          <p className="mt-1 max-w-[62ch] text-sm leading-6 text-muted-foreground">
            Live hypotheses, tournament standings, and final synthesis recorded for this research session.
          </p>
        </div>
      </div>

      {/* Live Hypotheses & Elo Leaderboard Section */}
      <div className="mt-8">
        <OverviewSection
          title="Live tournament standings & hypotheses"
          note="Hypotheses dynamically progress from draft to peer review to head-to-head tournament ranking."
        >
          <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start lg:gap-8">
            <HypothesisList
              hypotheses={hypotheses}
              selectedId={selectedHypothesis?.id}
              detailsId={detailsId}
              onSelect={setSelectedId}
              title="Elo Leaderboard"
              description="Live standings updated in real time."
            />
            {selectedHypothesis ? (
              <div
                id={detailsId}
                className="flex flex-col gap-5 rounded-2xl border border-border bg-card p-6 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs font-semibold tabular-nums text-muted-foreground">
                      #{selectedHypothesis.rank}
                    </span>
                    <HypothesisStateBadge state={selectedHypothesis.state} />
                    {selectedHypothesis.elo != null && (
                      <span className="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-xs font-semibold tabular-nums text-foreground">
                        Elo {Math.round(selectedHypothesis.elo)}
                      </span>
                    )}
                    {selectedHypothesis.matchesPlayed != null && selectedHypothesis.matchesPlayed > 0 && (
                      <span className="text-xs text-muted-foreground tabular-nums">
                        {selectedHypothesis.matchesPlayed}{' '}
                        {selectedHypothesis.matchesPlayed === 1 ? 'match' : 'matches'}
                      </span>
                    )}
                  </div>
                  <Link
                    to={`/research/${sessionId}/results?hypothesis=${encodeURIComponent(selectedHypothesis.id)}`}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline"
                  >
                    View evaluation
                    <ArrowRight className="size-3.5" />
                  </Link>
                </div>

                <div>
                  <h3 className="text-lg font-semibold tracking-tight text-foreground">
                    {selectedHypothesis.title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {selectedHypothesis.summary}
                  </p>
                </div>

                {selectedHypothesis.abstract && (
                  <div className="rounded-xl border border-border/80 bg-background/60 p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Scientific Abstract &amp; Rationale
                    </h4>
                    <p className="mt-1.5 whitespace-pre-line text-sm leading-6 text-foreground/90">
                      {selectedHypothesis.abstract}
                    </p>
                  </div>
                )}

                {selectedHypothesis.dataSummary?.metric ? (
                  <div className="rounded-xl border border-border/80 bg-background/60 p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Biomarker Evidence
                    </h4>
                    <p className="mt-1 text-sm text-foreground">
                      {selectedHypothesis.dataSummary.description || 'Survival correlation analysis'}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-4 text-xs text-muted-foreground">
                      <span>
                        Metric:{' '}
                        <strong className="text-foreground">
                          {selectedHypothesis.dataSummary.metric}
                        </strong>
                      </span>
                      {selectedHypothesis.dataSummary.unit && (
                        <span>
                          Unit:{' '}
                          <strong className="text-foreground">
                            {selectedHypothesis.dataSummary.unit}
                          </strong>
                        </span>
                      )}
                      <span>
                        Points:{' '}
                        <strong className="text-foreground">
                          {selectedHypothesis.dataPoints?.length ?? 0}
                        </strong>
                      </span>
                    </div>
                  </div>
                ) : null}

                {selectedHypothesis.sources && selectedHypothesis.sources.length > 0 && (
                  <div className="text-xs text-muted-foreground">
                    Supported by {selectedHypothesis.sources.length} cited source
                    {selectedHypothesis.sources.length === 1 ? '' : 's'}.
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Select a hypothesis to inspect its details and evidence.
              </div>
            )}
          </div>
        </OverviewSection>
      </div>

      {/* Synthesis Section */}
      <div className="mt-12 border-t border-border pt-10">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          Executive Synthesis
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Comprehensive synthesis compiled across validated research directions.
        </p>

        {loadingSynthesis && (
          <p className="mt-6 text-sm text-muted-foreground">Loading the research synthesis…</p>
        )}
        {synthesisError && (
          <p role="alert" className="mt-6 text-sm text-muted-foreground">
            {synthesisError}
          </p>
        )}
        {!loadingSynthesis && !synthesisError && overview === null ? (
          <div className="mt-6 rounded-xl border border-border bg-card p-5">
            <p className="text-sm font-medium text-foreground">
              {session?.status === 'running'
                ? 'Synthesis in progress'
                : 'No synthesis available yet'}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {session?.status === 'running'
                ? 'Agents are currently generating and ranking hypotheses. The final executive synthesis will appear here once all phases complete.'
                : 'This session has not produced a final research synthesis.'}
            </p>
          </div>
        ) : overview ? (
          <>
            {(overview.sessionId !== null || generatedAt !== null) && (
              <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-2 text-[0.8125rem] leading-5">
                {overview.sessionId !== null && (
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">Session</dt>
                    <dd className="break-all text-foreground">{overview.sessionId}</dd>
                  </div>
                )}
                {generatedAt !== null && (
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">Synthesis written</dt>
                    <dd className="text-foreground">{generatedAt}</dd>
                  </div>
                )}
              </dl>
            )}

            <div className="mt-8 space-y-10">
              {overview.executiveSummary && (
                <OverviewSection title="Executive summary">
                  <ExecutiveSummary
                    summary={overview.executiveSummary}
                    onCitationSelect={selectCitation}
                  />
                </OverviewSection>
              )}

              <OverviewSection
                title={
                  overview.directions.length === 1
                    ? 'Main research direction'
                    : 'Main research directions'
                }
                note={
                  overview.directions.length > 0
                    ? 'Each direction carries its own claim, open questions and proposed first experiment.'
                    : undefined
                }
              >
                {overview.directions.length === 0 ? (
                  <p className="text-sm leading-6 text-muted-foreground">
                    This synthesis records no research directions.
                  </p>
                ) : (
                  <div className="space-y-12">
                    {overview.directions.map((direction) => (
                      <ResearchDirectionView
                        key={direction.id}
                        direction={direction}
                        onCitationSelect={selectCitation}
                      />
                    ))}
                  </div>
                )}
              </OverviewSection>

              {overview.convergence && (
                <OverviewSection title="Convergence and divergence">
                  <ConvergenceSection
                    body={overview.convergence}
                    onCitationSelect={selectCitation}
                  />
                </OverviewSection>
              )}

              {overview.caveats && (
                <OverviewSection
                  title="Caveats and limitations"
                  note="What the workflow did not cover, and where a domain expert is most likely to disagree."
                >
                  <LimitationsSection body={overview.caveats} onCitationSelect={selectCitation} />
                </OverviewSection>
              )}

              <OverviewSection
                title="Sources"
                note={
                  overview.sources.length > 0
                    ? `${overview.sources.length} references. Every citation in this report points into this list.`
                    : undefined
                }
              >
                <ResearchSources sources={overview.sources} highlight={highlight} />
              </OverviewSection>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
