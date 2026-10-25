import { ArrowUpRight, CheckCircle2, FileText, Link2, Quote } from 'lucide-react'
import { Link } from 'react-router'
import { EVIDENCE_TYPE_STYLES, parsePassageAnchor } from '@/features/research/sourceUtils'
import { cn } from '@/lib/utils'
import type { SourceRecord } from '@/types/research'

interface SourceCardProps {
  source: SourceRecord
  hypothesis?: {
    id: string
    rank?: number
    title?: string
  }
  sessionId?: string
}

export function SourceCard({ source, hypothesis, sessionId }: SourceCardProps) {
  const meta = [source.publication, source.year].filter(Boolean).join(' · ')
  const passage = parsePassageAnchor(source.url)
  const isVerified = Boolean(source.url || source.verified)
  const typeStyle = EVIDENCE_TYPE_STYLES[source.evidenceType] ?? {
    bg: 'bg-muted',
    text: 'text-muted-foreground',
    border: 'border-border',
  }

  return (
    <article className="rounded-xl border border-border bg-secondary/50 p-5 transition-colors sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <h4 className="min-w-0 flex-1 text-[0.9375rem] leading-6 font-semibold text-foreground">
          {source.title}
        </h4>
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={cn(
              'inline-flex h-6 items-center rounded-md border px-2 text-xs font-medium whitespace-nowrap',
              typeStyle.bg,
              typeStyle.text,
              typeStyle.border,
            )}
          >
            {source.evidenceType}
          </span>
          {isVerified ? (
            <span className="inline-flex h-6 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 text-xs font-medium whitespace-nowrap text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="size-3" />
              Verified
            </span>
          ) : (
            <span className="inline-flex h-6 items-center rounded-md border border-border bg-muted/40 px-2 text-xs whitespace-nowrap text-muted-foreground">
              Unverified
            </span>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-muted-foreground">
        <span>{meta}</span>
        {passage.displayAnchor && (
          <span className="inline-flex items-center gap-1 rounded border border-border/80 bg-background/60 px-1.5 py-0.5 font-mono text-[0.6875rem] text-foreground/80">
            <Link2 className="size-3 text-brand" />
            Anchor: {passage.displayAnchor}
          </span>
        )}
      </div>

      {source.description ? (
        <figure className="mt-3.5 rounded-lg border-s-2 border-brand/80 bg-card/60 p-3.5 text-sm leading-6 text-foreground/90">
          <div className="flex items-start gap-2">
            <Quote className="mt-0.5 size-4 shrink-0 text-brand/70" />
            <blockquote className="font-serif italic text-foreground/85">
              {source.description}
            </blockquote>
          </div>
        </figure>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm">
        <div>
          {source.url ? (
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-sm font-medium text-brand underline decoration-brand/60 underline-offset-4 outline-none hover:decoration-brand focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {passage.isEuropePmc ? 'Open on Europe PMC' : 'Open source paper'}
              <ArrowUpRight aria-hidden="true" className="size-4" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <FileText className="size-3.5" />
              {source.publication || 'Source link unavailable'}
            </span>
          )}
        </div>

        {hypothesis && sessionId && (
          <div className="text-xs text-muted-foreground">
            Linked to{' '}
            <Link
              to={`/research/${sessionId}/results?hypothesis=${hypothesis.id}`}
              className="font-medium text-brand hover:underline"
            >
              Hypothesis {hypothesis.rank ? `#${hypothesis.rank}` : hypothesis.id.slice(0, 8)}
            </Link>
          </div>
        )}
      </div>
    </article>
  )
}
