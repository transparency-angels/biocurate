import type { Citation } from '@/types/researchOverview'
import { PROSE_WIDTH } from './OverviewSection'
import { ScientificText } from './ScientificText'

interface LimitationsSectionProps {
  body: string
  onCitationSelect?: (citation: Citation) => void
}

/**
 * What the workflow did not cover, and where it may be wrong. Set at the same size as
 * the rest of the report, with a marked edge, so it is not read as a footnote.
 */
export function LimitationsSection({ body, onCitationSelect }: LimitationsSectionProps) {
  return (
    <div className={`${PROSE_WIDTH} border-s-2 border-amber/60 ps-5`}>
      <ScientificText onCitationSelect={onCitationSelect}>{body}</ScientificText>
    </div>
  )
}
