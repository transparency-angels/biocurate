import { ArrowUpRight, CheckCircle2, Link2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { parsePassageAnchor } from '@/features/research/sourceUtils'
import type { Citation, OverviewSource } from '@/types/researchOverview'
import { sourceElementId } from './sourceAnchor'

interface ResearchSourcesProps {
  sources: OverviewSource[]
  /** The citation a reader last followed, so its source and excerpt can be marked */
  highlight: Citation | null
}

function Meta({ source }: { source: OverviewSource }) {
  const parts: string[] = []
  if (source.year !== null) parts.push(String(source.year))
  if (source.doi !== null) parts.push(`DOI ${source.doi}`)
  // Year and DOI are often absent; the line disappears rather than showing placeholders
  if (parts.length === 0) return null
  return <p className="mt-1 text-[0.8125rem] leading-5 break-words text-muted-foreground">{parts.join(' · ')}</p>
}

const squash = (value: string) => value.replace(/\s+/g, ' ').trim().toLowerCase()

/**
 * In the exports seen so far the summary bullets are sentence fragments cut from the
 * excerpt printed underneath them, so showing both prints the same words twice. A bullet
 * that the quoted lines already contain is dropped; anything the excerpts do not cover
 * is kept.
 */
function uncoveredBullets(source: OverviewSource): string[] {
  if (source.excerpts.length === 0) return source.bullets
  const quoted = squash(source.excerpts.map((excerpt) => excerpt.text).join(' '))
  return source.bullets.filter((bullet) => !quoted.includes(squash(bullet)))
}

function SourceEntry({ source, highlight }: { source: OverviewSource; highlight: Citation | null }) {
  const isTarget = highlight?.sourceId === source.id
  const bullets = uncoveredBullets(source)
  const passage = parsePassageAnchor(source.url)
  const isVerified = Boolean(source.url || source.doi)

  return (
    <li
      id={sourceElementId(source.id)}
      // Focusable only by script, so following a citation moves the keyboard here too
      tabIndex={-1}
      className={cn(
        'scroll-mt-20 rounded-xl border bg-secondary/40 p-5 transition-colors duration-300 sm:p-6',
        'motion-reduce:transition-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none',
        isTarget ? 'border-brand/60 bg-brand/5' : 'border-border',
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
        <div className="flex min-w-0 flex-1 items-start gap-2.5">
          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[0.8125rem] leading-5 font-medium text-muted-foreground tabular-nums">
            {source.id}
          </span>
          <h3 className="min-w-0 flex-1 text-[0.9375rem] leading-6 font-semibold text-balance text-foreground">
            {source.title}
          </h3>
        </div>
        <div className="flex items-center gap-1.5">
          {isVerified ? (
            <span className="inline-flex h-5.5 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 text-[0.6875rem] font-medium text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="size-3" />
              Verified
            </span>
          ) : (
            <span className="inline-flex h-5.5 items-center rounded-md border border-border bg-muted/40 px-2 text-[0.6875rem] text-muted-foreground">
              Unverified
            </span>
          )}
        </div>
      </div>
      <Meta source={source} />

      {passage.displayAnchor && (
        <div className="mt-2">
          <span className="inline-flex items-center gap-1 rounded border border-border/80 bg-background/60 px-1.5 py-0.5 font-mono text-[0.6875rem] text-foreground/80">
            <Link2 className="size-3 text-brand" />
            Anchor: {passage.displayAnchor}
          </span>
        </div>
      )}

      {bullets.length > 0 && (
        <ul className="mt-3 space-y-1.5 ps-5 text-sm leading-6 list-disc text-foreground/85 marker:text-faint">
          {bullets.map((bullet, index) => (
            <li key={index}>{bullet}</li>
          ))}
        </ul>
      )}

      {source.excerpts.length > 0 && (
        <div className="mt-4 space-y-2.5">
          {source.excerpts.map((excerpt, index) => {
            const isCited = isTarget && highlight?.lineRange !== null && highlight?.lineRange === excerpt.lineRange
            return (
              <figure
                key={index}
                className={cn(
                  'border-s-2 ps-4 transition-colors duration-300 motion-reduce:transition-none',
                  isCited ? 'border-brand' : 'border-border',
                )}
              >
                {excerpt.lineRange && (
                  <figcaption className="text-xs leading-5 text-faint tabular-nums">
                    Lines {excerpt.lineRange.replace(/L/g, '')}
                    {isCited && <span className="ms-2 text-brand">cited here</span>}
                  </figcaption>
                )}
                <blockquote className="mt-1 font-serif text-[0.9375rem] leading-7 whitespace-pre-line text-foreground/85">
                  {excerpt.text}
                </blockquote>
              </figure>
            )
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {source.url ? (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-sm font-medium text-brand underline decoration-brand/60 underline-offset-4 outline-none hover:decoration-brand focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {passage.isEuropePmc ? 'Open on Europe PMC' : 'Open source'}
            <ArrowUpRight aria-hidden="true" className="size-4" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <span className="text-faint">Source link unavailable</span>
        )}
        {source.referencedBy.length > 0 && (
          <p className="text-[0.8125rem] leading-5 break-all text-muted-foreground">
            Cited by{' '}
            <span className="font-medium text-foreground/80">
              {source.referencedBy.join(', ')}
            </span>
          </p>
        )}
      </div>
    </li>
  )
}

/** The reference list every citation in the report points into. */
export function ResearchSources({ sources, highlight }: ResearchSourcesProps) {
  if (sources.length === 0) {
    return <p className="text-sm leading-6 text-muted-foreground">This report lists no sources.</p>
  }

  return (
    <ol className="space-y-3">
      {sources.map((source) => (
        <SourceEntry key={source.id} source={source} highlight={highlight} />
      ))}
    </ol>
  )
}
