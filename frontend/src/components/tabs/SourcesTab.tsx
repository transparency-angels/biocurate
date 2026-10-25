import { useMemo, useState } from 'react'
import { CheckCircle2, Filter } from 'lucide-react'
import type { Hypothesis } from '@/types/research'
import { SourceCard } from './SourceCard'
import { cn } from '@/lib/utils'

export function SourcesTab({
  hypothesis,
  sessionId,
}: {
  hypothesis: Hypothesis
  sessionId?: string
}) {
  const { sources } = hypothesis
  const [filterType, setFilterType] = useState<string>('all')

  const verifiedCount = useMemo(() => {
    return sources.filter((s) => s.url || s.verified).length
  }, [sources])

  const evidenceCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    sources.forEach((s) => {
      counts[s.evidenceType] = (counts[s.evidenceType] || 0) + 1
    })
    return counts
  }, [sources])

  const filteredSources = useMemo(() => {
    if (filterType === 'all') return sources
    if (filterType === 'verified') return sources.filter((s) => s.url || s.verified)
    return sources.filter((s) => s.evidenceType === filterType)
  }, [sources, filterType])

  return (
    <div className="px-5 py-6 sm:px-8">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Verifiable literature & dataset records
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Passage-level citations and grounded evidence supporting Hypothesis #{hypothesis.rank}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="size-3" />
            {verifiedCount} verified
          </span>
          <span className="rounded-md border border-border bg-secondary/50 px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
            {sources.length} {sources.length === 1 ? 'total record' : 'total records'}
          </span>
        </div>
      </div>

      {sources.length > 2 && (
        <div className="mt-4 flex flex-wrap items-center gap-1.5 border-y border-border/60 py-2.5">
          <span className="flex items-center gap-1 text-xs text-muted-foreground pe-1">
            <Filter className="size-3" />
            Filter:
          </span>
          <button
            type="button"
            onClick={() => setFilterType('all')}
            className={cn(
              'rounded-md px-2 py-0.5 text-xs font-medium transition-colors',
              filterType === 'all'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            All ({sources.length})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('verified')}
            className={cn(
              'rounded-md px-2 py-0.5 text-xs font-medium transition-colors',
              filterType === 'verified'
                ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            Verified ({verifiedCount})
          </button>
          {Object.entries(evidenceCounts).map(([type, count]) => (
            <button
              key={type}
              type="button"
              onClick={() => setFilterType(type)}
              className={cn(
                'rounded-md px-2 py-0.5 text-xs font-medium transition-colors',
                filterType === type
                  ? 'bg-secondary text-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {type} ({count})
            </button>
          ))}
        </div>
      )}

      {filteredSources.length > 0 ? (
        <ul className="mt-5 space-y-3.5">
          {filteredSources.map((source) => (
            <li key={source.id}>
              <SourceCard
                source={source}
                hypothesis={{
                  id: hypothesis.id,
                  rank: hypothesis.rank,
                  title: hypothesis.title,
                }}
                sessionId={sessionId}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-5 rounded-xl border border-border px-5 py-6 text-sm text-muted-foreground">
          {sources.length === 0
            ? 'No source records cited for this hypothesis.'
            : 'No source records matching the selected filter.'}
        </p>
      )}
    </div>
  )
}
