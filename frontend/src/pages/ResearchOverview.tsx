import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { ConvergenceSection } from '@/components/overview/ConvergenceSection'
import { ExecutiveSummary } from '@/components/overview/ExecutiveSummary'
import { LimitationsSection } from '@/components/overview/LimitationsSection'
import { OverviewSection } from '@/components/overview/OverviewSection'
import { ResearchDirectionView } from '@/components/overview/ResearchDirectionView'
import { ResearchSources } from '@/components/overview/ResearchSources'
import { sourceElementId } from '@/components/overview/sourceAnchor'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { getSynthesis, normaliseSynthesis } from '@/services/api'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import type { Citation } from '@/types/researchOverview'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'long' })

function formatGeneratedAt(iso: string | null) {
  if (iso === null) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : dateFormat.format(date)
}

export function ResearchOverview() {
  const { sessionId } = useParams()
  const [highlight, setHighlight] = useState<Citation | null>(null)
  const [overview, setOverview] = useState<ReturnType<typeof normaliseSynthesis>>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!sessionId) return
    let active = true
    getSynthesis(sessionId).then((payload) => { if (active) setOverview(normaliseSynthesis(payload)) })
      .catch((e: Error) => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [sessionId])
  useDocumentTitle('Research overview')

  // Jumps to the cited source and marks it, so a citation can be checked where it lands
  const selectCitation = useCallback((citation: Citation) => {
    const element = document.getElementById(sourceElementId(citation.sourceId))
    if (!element) return
    setHighlight(citation)
    element.focus({ preventScroll: true })
    // Instant, like following a footnote: the reference list can be a whole screen away,
    // and animating that distance loses the reader. The highlight says where they landed.
    element.scrollIntoView({ behavior: 'auto', block: 'start' })
  }, [])

  const generatedAt = formatGeneratedAt(overview?.generatedAt ?? null)

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId ?? ''} />
      <div className="mt-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Research overview</h1>
          </div>
          <p className="mt-1 max-w-[62ch] text-sm leading-6 text-muted-foreground">
            The final synthesis recorded for this research session.
          </p>
        </div>
      </div>

      {loading && <p className="mt-8 text-sm text-muted-foreground">Loading the research synthesis…</p>}
      {error && <p role="alert" className="mt-8 text-sm text-muted-foreground">{error}</p>}
      {!loading && !error && overview === null ? (
        <p className="mt-8 border-t border-border pt-8 text-sm leading-6 text-muted-foreground">
          No synthesis is available for this session.
        </p>
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
                <ExecutiveSummary summary={overview.executiveSummary} onCitationSelect={selectCitation} />
              </OverviewSection>
            )}

            <OverviewSection
              title={overview.directions.length === 1 ? 'Main research direction' : 'Main research directions'}
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
                <ConvergenceSection body={overview.convergence} onCitationSelect={selectCitation} />
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
  )
}
