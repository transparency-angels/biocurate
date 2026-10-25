import { FlaskConical } from 'lucide-react'
import type { Citation } from '@/types/researchOverview'
import { PROSE_WIDTH } from './OverviewSection'
import { ScientificText } from './ScientificText'

interface ProposedExperimentProps {
  experiment: string
  onCitationSelect?: (citation: Citation) => void
}

/**
 * A suggested next step, never a result. The label and the line under it say so, so the
 * block cannot be read as work that has been carried out.
 */
export function ProposedExperiment({ experiment, onCitationSelect }: ProposedExperimentProps) {
  return (
    <div className={`${PROSE_WIDTH} rounded-xl border border-border bg-secondary/40 p-5 sm:p-6`}>
      <div className="flex items-center gap-2">
        <FlaskConical aria-hidden="true" strokeWidth={1.75} className="size-4 text-teal" />
        <h4 className="text-[0.9375rem] leading-6 font-semibold text-foreground">Proposed experiment</h4>
      </div>
      <p className="mt-1 text-[0.8125rem] leading-5 text-muted-foreground">
        Suggested by the research workflow. It has not been carried out, and no result is reported here.
      </p>
      <div className="mt-4">
        <ScientificText onCitationSelect={onCitationSelect}>{experiment}</ScientificText>
      </div>
    </div>
  )
}
