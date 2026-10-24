import { useId } from 'react'
import type { Citation, ResearchDirection } from '@/types/researchOverview'
import { OpenQuestions } from './OpenQuestions'
import { PROSE_WIDTH } from './OverviewSection'
import { ProposedExperiment } from './ProposedExperiment'
import { ScientificText } from './ScientificText'

interface ResearchDirectionViewProps {
  direction: ResearchDirection
  onCitationSelect?: (citation: Citation) => void
}

function SubHeading({ children }: { children: string }) {
  return <h4 className="text-[0.9375rem] leading-6 font-semibold text-foreground">{children}</h4>
}

/** One research direction: its claim, the case for it, what is unresolved, what to run next. */
export function ResearchDirectionView({ direction, onCitationSelect }: ResearchDirectionViewProps) {
  const headingId = useId()
  const { index, title, claim, whyPromising, openQuestions, firstExperiment, supportingHypotheses, citations } =
    direction

  return (
    <article aria-labelledby={headingId} className="scroll-mt-20">
      <h3
        id={headingId}
        className="max-w-[46ch] text-[1.0625rem] leading-7 font-semibold tracking-[-0.01em] text-balance text-foreground sm:text-[1.1875rem]"
      >
        <span className="text-faint tabular-nums">{index}. </span>
        <ScientificTextInline>{title}</ScientificTextInline>
      </h3>

      <div className="mt-5 space-y-7">
        {claim && (
          <div>
            <SubHeading>The claim</SubHeading>
            <div className={`${PROSE_WIDTH} mt-2`}>
              <ScientificText onCitationSelect={onCitationSelect}>{claim}</ScientificText>
            </div>
          </div>
        )}

        {whyPromising && (
          <div>
            <SubHeading>Why it is promising</SubHeading>
            <div className={`${PROSE_WIDTH} mt-2`}>
              <ScientificText onCitationSelect={onCitationSelect}>{whyPromising}</ScientificText>
            </div>
          </div>
        )}

        {openQuestions.length > 0 && (
          <div>
            <SubHeading>Open questions</SubHeading>
            <div className="mt-2">
              <OpenQuestions parts={openQuestions} onCitationSelect={onCitationSelect} />
            </div>
          </div>
        )}

        {firstExperiment && (
          <ProposedExperiment experiment={firstExperiment} onCitationSelect={onCitationSelect} />
        )}

        {(supportingHypotheses.length > 0 || citations.length > 0) && (
          <dl className="grid gap-x-8 gap-y-4 border-t border-border pt-5 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
            {supportingHypotheses.length > 0 && (
              <>
                <dt className="text-[0.8125rem] leading-6 text-muted-foreground">Supporting hypotheses</dt>
                <dd className="flex flex-wrap gap-1.5">
                  {supportingHypotheses.map((id) => (
                    <span
                      key={id}
                      className="rounded-md bg-secondary px-1.5 py-0.5 text-[0.8125rem] leading-5 break-all text-muted-foreground"
                    >
                      {id}
                    </span>
                  ))}
                </dd>
              </>
            )}
            {citations.length > 0 && (
              <>
                <dt className="text-[0.8125rem] leading-6 text-muted-foreground">Cited sources</dt>
                <dd className="flex flex-wrap gap-1.5">
                  {citations.map((citation) => (
                    <button
                      key={citation.raw}
                      type="button"
                      onClick={() => onCitationSelect?.(citation)}
                      className="rounded-md bg-secondary px-1.5 py-0.5 text-[0.8125rem] leading-5 font-medium whitespace-nowrap text-brand transition-colors outline-none hover:bg-brand/15 focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {citation.lineRange ? `${citation.sourceId} ${citation.lineRange}` : citation.sourceId}
                      <span className="sr-only"> (go to this source)</span>
                    </button>
                  ))}
                </dd>
              </>
            )}
          </dl>
        )}
      </div>
    </article>
  )
}

/** Titles carry italics and Greek letters too, but must stay on one line of markup. */
function ScientificTextInline({ children }: { children: string }) {
  return <ScientificText variant="ui" className="inline space-y-0 [&>p]:inline [&>p]:text-inherit">{children}</ScientificText>
}
