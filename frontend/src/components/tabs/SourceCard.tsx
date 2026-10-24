import { ArrowUpRight } from 'lucide-react'
import type { SourceRecord } from '@/types/research'

export function SourceCard({ source }: { source: SourceRecord }) {
  const meta = [source.publication, source.year].filter(Boolean).join(' · ')

  return (
    <article className="rounded-xl border border-border bg-secondary/60 p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <h4 className="min-w-0 text-[0.9375rem] leading-6 font-semibold text-foreground">{source.title}</h4>
        <span className="inline-flex h-6 flex-none items-center rounded-md border border-input px-2 text-xs whitespace-nowrap text-muted-foreground">
          {source.evidenceType}
        </span>
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted-foreground">{meta}</p>
      <p className="mt-3 text-sm leading-6 text-foreground/85">{source.description}</p>

      <div className="mt-4 text-sm">
        {source.url ? (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-sm font-medium text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Open source paper
            <ArrowUpRight aria-hidden="true" className="size-4" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <span className="text-faint">Source link unavailable</span>
        )}
      </div>
    </article>
  )
}
