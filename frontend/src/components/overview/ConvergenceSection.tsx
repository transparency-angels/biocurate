import type { Citation } from '@/types/researchOverview'
import { PROSE_WIDTH } from './OverviewSection'
import { ScientificText } from './ScientificText'

interface ConvergenceSectionProps {
  body: string
  onCitationSelect?: (citation: Citation) => void
}

/** How the directions relate: where the evidence meets, and where it splits. */
export function ConvergenceSection({ body, onCitationSelect }: ConvergenceSectionProps) {
  return (
    <div className={PROSE_WIDTH}>
      <ScientificText onCitationSelect={onCitationSelect}>{body}</ScientificText>
    </div>
  )
}
