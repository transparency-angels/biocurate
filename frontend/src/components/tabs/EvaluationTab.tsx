import { DemoNotice } from '@/components/DemoNotice'
import type { Hypothesis } from '@/types/research'

interface EvaluationTabProps {
  hypothesis: Hypothesis
  total: number
}

export function EvaluationTab({ hypothesis, total }: EvaluationTabProps) {
  return (
    <article className="px-5 py-6 sm:px-8 sm:py-8">
      <header>
        <p className="text-[0.8125rem] text-muted-foreground tabular-nums">
          Rank {hypothesis.rank} of {total}
        </p>
        <h2 className="mt-1 text-xl leading-7 font-semibold tracking-[-0.01em] text-balance text-foreground sm:text-[1.375rem]">
          {hypothesis.title}
        </h2>
        <div className="mt-3">
          <DemoNotice>Placeholder text for layout only. It is not a research finding.</DemoNotice>
        </div>
      </header>

      <div className="mt-6 border-t border-border pt-6">
        <div className="max-w-[68ch] space-y-7">
          <section>
            <h3 className="text-sm font-semibold text-foreground">Abstract</h3>
            <p className="mt-2 font-serif text-[1.0625rem] leading-7 text-foreground/90">{hypothesis.abstract}</p>
          </section>
          <section>
            <h3 className="text-sm font-semibold text-foreground">Research explanation</h3>
            <p className="mt-2 font-serif text-[1.0625rem] leading-7 text-foreground/90">{hypothesis.explanation}</p>
          </section>
        </div>
      </div>
    </article>
  )
}
