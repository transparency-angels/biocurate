import { useId } from 'react'
import type { Hypothesis } from '@/types/research'
import { HypothesisCard } from './HypothesisCard'

interface HypothesisListProps {
  hypotheses: Hypothesis[]
  selectedId?: string
  detailsId?: string
  onSelect?: (id: string) => void
  title?: string
  description?: string
}

export function HypothesisList({
  hypotheses,
  selectedId,
  detailsId = 'hypothesis-details',
  onSelect,
  title = 'Top hypotheses',
  description = 'Select an idea to inspect its evidence and rationale.',
}: HypothesisListProps) {
  const headingId = useId()

  return (
    <section aria-labelledby={headingId}>
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-base font-semibold text-foreground">{title}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs font-medium tabular-nums text-muted-foreground">{hypotheses.length}</span>
      </div>
      {hypotheses.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No hypotheses available yet. They will appear here dynamically as agents generate them.
        </div>
      ) : (
        <ol className="mt-4 flex flex-col gap-2">
          {hypotheses.map((hypothesis) => (
            <li key={hypothesis.id}>
              <HypothesisCard
                hypothesis={hypothesis}
                selected={hypothesis.id === selectedId}
                controls={detailsId}
                onSelect={onSelect}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
