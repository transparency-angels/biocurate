import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Hypothesis } from '@/types/research'

interface HypothesisCardProps {
  hypothesis: Hypothesis
  selected: boolean
  /** id of the details panel this card updates */
  controls: string
  onSelect: (id: string) => void
}

export function HypothesisCard({ hypothesis, selected, controls, onSelect }: HypothesisCardProps) {
  return (
    <button
      type="button"
      aria-current={selected ? 'true' : undefined}
      aria-controls={controls}
      onClick={() => onSelect(hypothesis.id)}
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
        <span className="block text-[0.9375rem] leading-6 font-medium text-foreground">
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
