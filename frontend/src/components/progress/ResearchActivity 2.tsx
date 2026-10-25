import { useId, useLayoutEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { AGENT_LABELS, type ActivityEntry } from '@/services/eventAdapter'
import { formatClockTime, toneDotClass } from './statusLabels'

/** How close to the bottom still counts as "following" the newest entries */
const FOLLOW_THRESHOLD_PX = 48

interface ResearchActivityProps {
  entries: ActivityEntry[]
  className?: string
}

/** Every event in time order. Follows new entries unless the reader has scrolled up. */
export function ResearchActivity({ entries, className }: ResearchActivityProps) {
  const headingId = useId()
  const scrollerRef = useRef<HTMLDivElement>(null)
  const followRef = useRef(true)

  useLayoutEffect(() => {
    const scroller = scrollerRef.current
    if (scroller && followRef.current) scroller.scrollTop = scroller.scrollHeight
  }, [entries.length])

  function handleScroll() {
    const scroller = scrollerRef.current
    if (!scroller) return
    followRef.current = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < FOLLOW_THRESHOLD_PX
  }

  return (
    <section
      aria-labelledby={headingId}
      className={cn('flex min-h-0 min-w-0 flex-col rounded-xl border border-border bg-card', className)}
    >
      <div className="flex items-baseline justify-between gap-4 px-5 pt-4 pb-3 sm:px-6">
        <h2 id={headingId} className="text-base font-semibold text-foreground">
          Research activity
        </h2>
        <p className="text-[0.8125rem] text-muted-foreground tabular-nums">
          {entries.length} {entries.length === 1 ? 'event' : 'events'}
        </p>
      </div>

      <div
        ref={scrollerRef}
        onScroll={handleScroll}
        tabIndex={0}
        aria-labelledby={headingId}
        role="region"
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-border px-5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset sm:px-6"
      >
        {entries.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">Waiting for the first event.</p>
        ) : (
          <ol className="divide-y divide-border">
            {entries.map((entry) => (
              <li key={entry.key} className="grid grid-cols-[0.375rem_minmax(0,1fr)] gap-x-3 py-3">
                <span aria-hidden="true" className={cn('mt-2 size-1.5 rounded-full', toneDotClass(entry.tone))} />
                <div className="min-w-0">
                  <div className="flex items-baseline gap-x-2">
                    <p className="min-w-0 truncate text-sm leading-5 font-medium text-foreground">
                      {entry.type}
                      {entry.agent && <span className="font-normal text-muted-foreground"> · {AGENT_LABELS[entry.agent]}</span>}
                    </p>
                    <time
                      dateTime={new Date(entry.ts).toISOString()}
                      className="ml-auto flex-none text-xs leading-5 text-faint tabular-nums"
                    >
                      {formatClockTime(entry.ts)}
                    </time>
                  </div>
                  <p className="mt-0.5 text-[0.8125rem] leading-5 break-words text-muted-foreground">{entry.description}</p>
                  {entry.error && (
                    <p className="mt-1 text-[0.8125rem] leading-5 break-words text-destructive">
                      <span className="sr-only">Error: </span>
                      {entry.error}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  )
}
