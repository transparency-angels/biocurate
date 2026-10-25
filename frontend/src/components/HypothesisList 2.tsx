import { useId } from 'react'
import type { Hypothesis } from '@/types/research'
import { HypothesisCard } from './HypothesisCard'

interface HypothesisListProps {
  hypotheses: Hypothesis[]
  selectedId: string
  detailsId: string
  onSelect: (id: string) => void
}

export function HypothesisList({ hypotheses, selectedId, detailsId, onSelect }: HypothesisListProps) {
  const headingId = useId()

  return (
    <section aria-labelledby={headingId}>
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-base font-semibold text-foreground">Top hypotheses</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">Select an idea to inspect its evidence and rationale.</p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs font-medium tabular-nums text-muted-foreground">{hypotheses.length}</span>
      </div>
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
    </section>
  )
}
