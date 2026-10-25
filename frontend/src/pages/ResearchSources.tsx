import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  ArrowUpRight,
  CheckCircle2,
  FileText,
  Link2,
  Quote,
  Search,
} from 'lucide-react'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { EVIDENCE_TYPE_STYLES, parsePassageAnchor } from '@/features/research/sourceUtils'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { cn } from '@/lib/utils'
import { getResearch, getSession, type SessionSnapshot } from '@/services/api'
import type { EvidenceType, Hypothesis, ResearchSession, SourceRecord } from '@/types/research'
import { NotFoundPage } from './NotFoundPage'

interface AggregatedSource extends SourceRecord {
  referencingHypotheses: Array<{
    id: string
    rank: number
    title: string
  }>
}

export function ResearchSources() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<ResearchSession | null>(null)
  const [sessionInfo, setSessionInfo] = useState<SessionSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<string>('all')

  const refresh = useCallback(() => {
    return Promise.all([
      getSession(sessionId),
      getResearch(sessionId, true).catch(() => null),
    ])
      .then(([storedSession, research]) => {
        setSessionInfo(storedSession)
        setSession(research)
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
      sessionInfo?.status === 'running'
        ? window.setInterval(load, 4000)
        : undefined
    return () => {
      active = false
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [refresh, sessionInfo?.status])

  useDocumentTitle('Literature sources')

  // Aggregate and deduplicate sources across all hypotheses
  const aggregatedSources: AggregatedSource[] = useMemo(() => {
    if (!session?.hypotheses) return []

    const map = new Map<string, AggregatedSource>()

    session.hypotheses.forEach((hyp: Hypothesis) => {
      ;(hyp.sources || []).forEach((src: SourceRecord) => {
        const key = src.url || src.title.toLowerCase().trim()
        const existing = map.get(key)
        const refEntry = {
          id: hyp.id,
          rank: hyp.rank,
          title: hyp.title,
        }

        if (existing) {
          if (!existing.referencingHypotheses.some((h) => h.id === hyp.id)) {
            existing.referencingHypotheses.push(refEntry)
          }
          if (!existing.description && src.description) {
            existing.description = src.description
          }
        } else {
          map.set(key, {
            ...src,
            referencingHypotheses: [refEntry],
          })
        }
      })
    })

    return Array.from(map.values())
  }, [session])

  // Compute metrics
  const verifiedCount = useMemo(() => {
    return aggregatedSources.filter((s) => s.url || s.verified).length
  }, [aggregatedSources])

  const europePmcCount = useMemo(() => {
    return aggregatedSources.filter((s) => s.url?.includes('europepmc.org')).length
  }, [aggregatedSources])

  const evidenceCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    aggregatedSources.forEach((s) => {
      counts[s.evidenceType] = (counts[s.evidenceType] || 0) + 1
    })
    return counts
  }, [aggregatedSources])

  // Filter and search
  const displayedSources = useMemo(() => {
    return aggregatedSources.filter((source) => {
      // Filter tab
      if (filterType === 'verified' && !source.url && !source.verified) return false
      if (filterType !== 'all' && filterType !== 'verified' && source.evidenceType !== filterType) {
        return false
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchTitle = source.title.toLowerCase().includes(q)
        const matchPub = (source.publication || '').toLowerCase().includes(q)
        const matchDesc = (source.description || '').toLowerCase().includes(q)
        const matchAnchor = (source.anchor || '').toLowerCase().includes(q)
        const matchHyp = source.referencingHypotheses.some((h) =>
          h.title.toLowerCase().includes(q),
        )
        return matchTitle || matchPub || matchDesc || matchAnchor || matchHyp
      }

      return true
    })
  }, [aggregatedSources, filterType, searchQuery])

  if (error && !session) {
    return <NotFoundPage title="Sources unavailable" message={error} />
  }

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />

      <header className="mt-5">
        <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">
          Literature sources & evidence grounding
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Traceable publications, Europe PMC passage snippets, and evidence anchors cited across
          hypotheses.
        </p>
      </header>

      {/* Metrics Row */}
      <section
        aria-label="Sources overview stats"
        className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:gap-4"
      >
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Total cited sources</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-foreground tabular-nums">
            {aggregatedSources.length}
          </p>
          <p className="mt-0.5 text-xs text-faint">
            Across {session?.hypotheses?.length ?? 0} hypotheses
          </p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Verified citations</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight text-emerald-600 dark:text-emerald-400 tabular-nums">
              {verifiedCount}
            </span>
            <span className="text-xs text-muted-foreground">
              {aggregatedSources.length > 0
                ? `${Math.round((verifiedCount / aggregatedSources.length) * 100)}%`
                : '–'}
            </span>
          </div>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-faint">
            <CheckCircle2 className="size-3 text-emerald-500" />
            Verified link / DOI
          </p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Europe PMC articles</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-foreground tabular-nums">
            {europePmcCount}
          </p>
          <p className="mt-0.5 text-xs text-faint">Passage-level anchors</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Clinical & datasets</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight text-foreground tabular-nums">
            {(evidenceCounts['Clinical study'] || 0) + (evidenceCounts['Dataset'] || 0)}
          </p>
          <p className="mt-0.5 text-xs text-faint">
            {evidenceCounts['Clinical study'] || 0} clinical · {evidenceCounts['Dataset'] || 0}{' '}
            datasets
          </p>
        </div>
      </section>

      {/* Filters & Search Toolbar */}
      <div className="mt-8 flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between sm:p-4">
        {/* Search */}
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search papers, excerpts, journals, or genes…"
            className="h-9 w-full rounded-lg border border-border bg-background ps-9 pe-3 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-brand focus:ring-1 focus:ring-brand"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
          <button
            type="button"
            onClick={() => setFilterType('all')}
            className={cn(
              'h-8 rounded-lg px-3 text-xs font-medium whitespace-nowrap transition-colors',
              filterType === 'all'
                ? 'bg-secondary font-semibold text-foreground'
                : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground',
            )}
          >
            All ({aggregatedSources.length})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('verified')}
            className={cn(
              'h-8 rounded-lg px-3 text-xs font-medium whitespace-nowrap transition-colors',
              filterType === 'verified'
                ? 'bg-emerald-500/15 font-semibold text-emerald-700 dark:text-emerald-300'
                : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground',
            )}
          >
            Verified ({verifiedCount})
          </button>
          {(['Clinical study', 'Dataset', 'Review', 'Experimental study'] as EvidenceType[]).map(
            (type) => {
              const count = evidenceCounts[type] || 0
              if (count === 0) return null
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => setFilterType(type)}
                  className={cn(
                    'h-8 rounded-lg px-3 text-xs font-medium whitespace-nowrap transition-colors',
                    filterType === type
                      ? 'bg-secondary font-semibold text-foreground'
                      : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground',
                  )}
                >
                  {type} ({count})
                </button>
              )
            },
          )}
        </div>
      </div>

      {/* Sources List */}
      <div className="mt-6">
        {loading && aggregatedSources.length === 0 ? (
          <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
            Loading literature citations…
          </div>
        ) : displayedSources.length === 0 ? (
          <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
            {aggregatedSources.length === 0
              ? 'No literature sources or datasets recorded yet.'
              : 'No sources match your active filter or search query.'}
          </div>
        ) : (
          <ul className="space-y-4">
            {displayedSources.map((source) => {
              const passage = parsePassageAnchor(source.url)
              const meta = [source.publication, source.year].filter(Boolean).join(' · ')
              const isVerified = Boolean(source.url || source.verified)
              const typeStyle = EVIDENCE_TYPE_STYLES[source.evidenceType] ?? {
                bg: 'bg-muted',
                text: 'text-muted-foreground',
                border: 'border-border',
              }

              return (
                <li
                  key={source.id}
                  className="rounded-xl border border-border bg-card p-5 transition-colors sm:p-6"
                >
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                    <h3 className="min-w-0 flex-1 text-base font-semibold leading-6 text-foreground">
                      {source.title}
                    </h3>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={cn(
                          'inline-flex h-6 items-center rounded-md border px-2 text-xs font-medium whitespace-nowrap',
                          typeStyle.bg,
                          typeStyle.text,
                          typeStyle.border,
                        )}
                      >
                        {source.evidenceType}
                      </span>
                      {isVerified ? (
                        <span className="inline-flex h-6 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 text-xs font-medium whitespace-nowrap text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="size-3" />
                          Verified
                        </span>
                      ) : (
                        <span className="inline-flex h-6 items-center rounded-md border border-border bg-muted/40 px-2 text-xs whitespace-nowrap text-muted-foreground">
                          Unverified
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>{meta}</span>
                    {passage.displayAnchor && (
                      <span className="inline-flex items-center gap-1 rounded border border-border/80 bg-background/80 px-1.5 py-0.5 font-mono text-[0.6875rem] text-foreground/80">
                        <Link2 className="size-3 text-brand" />
                        Anchor: {passage.displayAnchor}
                      </span>
                    )}
                  </div>

                  {source.description && (
                    <figure className="mt-3.5 rounded-lg border-s-2 border-brand/80 bg-secondary/40 p-3.5 text-sm leading-6 text-foreground/90">
                      <div className="flex items-start gap-2">
                        <Quote className="mt-0.5 size-4 shrink-0 text-brand/70" />
                        <blockquote className="font-serif italic text-foreground/85">
                          {source.description}
                        </blockquote>
                      </div>
                    </figure>
                  )}

                  <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border/60 pt-3 text-sm">
                    <div>
                      {source.url ? (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 rounded-sm text-xs font-medium text-brand underline decoration-brand/60 underline-offset-4 outline-none hover:decoration-brand focus-visible:ring-3 focus-visible:ring-ring/50"
                        >
                          {passage.isEuropePmc ? 'Open on Europe PMC' : 'Open source publication'}
                          <ArrowUpRight aria-hidden="true" className="size-3.5" />
                          <span className="sr-only">(opens in a new tab)</span>
                        </a>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <FileText className="size-3.5" />
                          Local attachment
                        </span>
                      )}
                    </div>

                    {source.referencingHypotheses.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                        <span>Cited in:</span>
                        {source.referencingHypotheses.map((h) => (
                          <Link
                            key={h.id}
                            to={`/research/${sessionId}/results?hypothesis=${h.id}`}
                            className="inline-flex items-center rounded bg-secondary px-1.5 py-0.5 font-medium text-foreground transition-colors hover:bg-brand/10 hover:text-brand"
                            title={h.title}
                          >
                            Hypothesis #{h.rank}
                          </Link>
                        ))}
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
