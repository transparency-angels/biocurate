import { cn } from '@/lib/utils'
import type { Citation } from '@/types/researchOverview'
import { PROSE_WIDTH } from './OverviewSection'
import { ScientificText } from './ScientificText'

interface ExecutiveSummaryProps {
  summary: string
  onCitationSelect?: (citation: Citation) => void
}

/** The report's opening statement, set at reading size rather than inside a card. */
export function ExecutiveSummary({ summary, onCitationSelect }: ExecutiveSummaryProps) {
  return (
    <ScientificText
      onCitationSelect={onCitationSelect}
      className={cn(PROSE_WIDTH, 'text-[1.125rem] leading-[1.8] text-foreground/95')}
    >
      {summary}
    </ScientificText>
  )
}
