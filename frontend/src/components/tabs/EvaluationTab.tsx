import type { Hypothesis } from '@/types/research'
import { Lightbulb, Microscope } from 'lucide-react'
import { ScientificText } from '@/components/overview/ScientificText'

interface EvaluationTabProps {
  hypothesis: Hypothesis
  total: number
}

export function EvaluationTab({ hypothesis, total }: EvaluationTabProps) {
  return (
    <article className="px-5 py-6 sm:px-8 sm:py-8">
      <header className="relative overflow-hidden rounded-2xl border border-brand/15 bg-gradient-to-br from-brand/[0.07] via-card to-card p-5 sm:p-7">
        <div aria-hidden="true" className="absolute -right-8 -top-10 size-36 rounded-full border border-brand/10" />
        <div className="relative flex items-center gap-2 text-xs font-medium text-brand">
          <Lightbulb aria-hidden="true" className="size-4" />
          <span>Hypothesis {hypothesis.rank} <span className="text-muted-foreground">of {total}</span></span>
        </div>
        <h2 className="relative mt-3 max-w-[38ch] text-xl leading-8 font-semibold tracking-[-0.02em] text-balance text-foreground sm:text-2xl">
          {hypothesis.title}
        </h2>
      </header>

      <div className="mx-auto mt-8 max-w-[72ch] space-y-8">
          <section aria-labelledby="hypothesis-claim" className="relative border-l-2 border-brand/40 pl-5 sm:pl-6">
            <h3 id="hypothesis-claim" className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Core claim</h3>
            <div className="mt-3"><ScientificText>{hypothesis.abstract}</ScientificText></div>
          </section>
          <section aria-labelledby="hypothesis-rationale" className="rounded-2xl bg-muted/45 p-5 sm:p-6">
            <h3 id="hypothesis-rationale" className="flex items-center gap-2 text-sm font-semibold text-foreground"><Microscope aria-hidden="true" className="size-4 text-brand" />Research rationale</h3>
            <div className="mt-3"><ScientificText>{hypothesis.explanation}</ScientificText></div>
          </section>
      </div>
    </article>
  )
}
