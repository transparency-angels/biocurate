import { useId, type ReactNode } from 'react'
import { useNow } from '@/hooks/useResearchProgress'
import type { ResearchProgress } from '@/services/eventAdapter'
import { StatusPill } from './StatusPill'
import { PHASE_STATUS, formatClockTime, formatDuration } from './statusLabels'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

interface ResearchSessionHeaderProps {
  /** The full question as submitted; the session_started goal is cut to 200 characters */
  question: string
  progress: ResearchProgress
  /** Rendered at the foot of the panel, e.g. the demo controls */
  children?: ReactNode
}

function Fact({ label, children, note }: { label: string; children: ReactNode; note?: string }) {
  return (
    <div className="min-w-0 bg-card px-5 py-3 sm:px-6">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-[0.9375rem] leading-6 text-foreground tabular-nums">{children}</dd>
      {note && <dd className="text-xs leading-5 text-faint">{note}</dd>}
    </div>
  )
}

const dash = <span className="text-faint">—</span>

export function ResearchSessionHeader({ question, progress, children }: ResearchSessionHeaderProps) {
  const headingId = useId()
  const { phase, startedAt, endedAt, budgetUsd } = progress
  const working = phase === 'preparing' || phase === 'running'
  const now = useNow(startedAt !== null && endedAt === null)
  const status = PHASE_STATUS[phase]

  return (
    <section aria-labelledby={headingId} className="overflow-hidden rounded-xl border border-border bg-card">
      {/* No reliable overall percentage exists, so progress is shown as indeterminate */}
      <div
        role={working ? 'progressbar' : undefined}
        aria-label={working ? 'Research in progress' : undefined}
        className="h-0.5 overflow-hidden"
      >
        {working && <div className="h-full w-2/5 bg-brand/70 motion-safe:animate-indeterminate" />}
      </div>

      <div className="px-5 pt-3.5 pb-4 sm:px-6">
        <h2 id={headingId} className="text-xs text-muted-foreground">
          Your research question
        </h2>
        <p className="mt-1.5 font-serif text-[1.0625rem] leading-7 break-words whitespace-pre-line text-foreground">
          {question}
        </p>
      </div>

      {/* The 1px gap over a border-coloured ground draws the dividers in both layouts */}
      <dl className="grid grid-cols-2 gap-px border-t border-border bg-border lg:grid-cols-4">
        <Fact label="Status">
          <StatusPill tone={status.tone} className="mt-0.5">
            {status.label}
          </StatusPill>
        </Fact>
        <Fact label="Elapsed">{startedAt !== null ? formatDuration((endedAt ?? Math.max(now, startedAt)) - startedAt) : dash}</Fact>
        <Fact label="Started">{startedAt !== null ? <time dateTime={new Date(startedAt).toISOString()}>{formatClockTime(startedAt)}</time> : dash}</Fact>
        <Fact label="Budget limit" note={budgetUsd !== null ? 'Spending so far is not in the event stream' : undefined}>
          {budgetUsd !== null ? usd.format(budgetUsd) : dash}
        </Fact>
      </dl>

      {children}
    </section>
  )
}
