import type { Citation, OpenQuestionPart } from '@/types/researchOverview'
import { PROSE_WIDTH } from './OverviewSection'
import { ScientificText } from './ScientificText'

interface OpenQuestionsProps {
  parts: OpenQuestionPart[]
  onCitationSelect?: (citation: Citation) => void
}

/**
 * What the direction still rests on, in the backend's own division: what would have to
 * be true, and what would falsify it. Labels are the ones the report wrote; parts that
 * carry no label are shown as plain prose.
 */
export function OpenQuestions({ parts, onCitationSelect }: OpenQuestionsProps) {
  if (parts.length === 0) return null

  return (
    <dl className={`${PROSE_WIDTH} space-y-5`}>
      {parts.map((part, index) => (
        <div key={index}>
          {part.label && (
            <dt className="text-[0.9375rem] leading-6 font-semibold text-foreground">{part.label}</dt>
          )}
          <dd className={part.label ? 'mt-1.5' : undefined}>
            <ScientificText onCitationSelect={onCitationSelect}>{part.text}</ScientificText>
          </dd>
        </div>
      ))}
    </dl>
  )
}
