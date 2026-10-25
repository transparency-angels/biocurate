import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Hypothesis } from '@/types/research'

interface HypothesisCardProps {
  hypothesis: Hypothesis
  selected?: boolean
  /** id of the details panel this card updates */
  controls?: string
  onSelect?: (id: string) => void
}

export function HypothesisStateBadge({ state }: { state?: Hypothesis['state'] }) {
  if (!state) return null

  switch (state) {
    case 'draft':
      return (
        <span className="inline-flex items-center rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
          Draft
        </span>
      )
    case 'reviewed':
      return (
        <span className="inline-flex items-center rounded-md border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-400">
          Reviewed
        </span>
      )
    case 'in_tournament':
    case 'pinned':
      return (
        <span className="inline-flex items-center rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
          In Tournament
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground capitalize">
          {state}
        </span>
      )
  }
}

export function HypothesisCard({ hypothesis, selected, controls, onSelect }: HypothesisCardProps) {
  return (
    <button
      type="button"
      aria-current={selected ? 'true' : undefined}
      aria-controls={controls}
      onClick={() => onSelect?.(hypothesis.id)}
      className={cn(
        'flex w-full items-start gap-3.5 rounded-xl border p-4 text-left transition-colors outline-none',
        'focus-visible:ring-3 focus-visible:ring-ring/50',
        selected
          ? 'border-brand/35 bg-brand/[0.045] shadow-sm shadow-brand/5'
          : 'border-border/80 bg-card hover:border-input hover:bg-secondary/70',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums',
          selected ? 'bg-brand text-brand-foreground shadow-sm' : 'bg-muted text-muted-foreground',
        )}
      >
        {hypothesis.rank}
      </span>
      <span className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <HypothesisStateBadge state={hypothesis.state} />
          {hypothesis.elo != null && (
            <span className="inline-flex items-center rounded bg-secondary px-1.5 py-0.5 text-[0.6875rem] font-semibold tabular-nums text-foreground">
              Elo {Math.round(hypothesis.elo)}
            </span>
          )}
          {hypothesis.matchesPlayed != null && hypothesis.matchesPlayed > 0 && (
            <span className="text-[0.6875rem] text-muted-foreground tabular-nums">
              {hypothesis.matchesPlayed} {hypothesis.matchesPlayed === 1 ? 'match' : 'matches'}
            </span>
          )}
        </div>
        <span className="mt-1 block text-[0.9375rem] leading-6 font-medium text-foreground">
          <span className="sr-only">Rank {hypothesis.rank}: </span>
          {hypothesis.title}
        </span>
        <span className="mt-0.5 line-clamp-2 block text-[0.8125rem] leading-5 text-muted-foreground">
          {hypothesis.summary}
        </span>
      </span>
      <ChevronRight
        aria-hidden="true"
        className={cn('mt-1.5 size-4 shrink-0', selected ? 'text-foreground' : 'text-faint')}
      />
    </button>
  )
}
