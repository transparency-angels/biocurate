import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface OverviewSectionProps {
  title: string
  /** One line under the heading, for what the section is rather than what it says */
  note?: string
  children: ReactNode
  className?: string
}

/** One titled part of the report. Keeps every section on the same rhythm. */
export function OverviewSection({ title, note, children, className }: OverviewSectionProps) {
  const headingId = useId()

  return (
    <section aria-labelledby={headingId} className={cn('border-t border-border pt-8', className)}>
      <h2 id={headingId} className="text-[1.1875rem] leading-7 font-semibold tracking-[-0.01em] text-foreground">
        {title}
      </h2>
      {note && <p className="mt-1 text-[0.8125rem] leading-5 text-muted-foreground">{note}</p>}
      <div className="mt-5">{children}</div>
    </section>
  )
}

/** The reading measure for long scientific prose: about 70 characters a line. */
export const PROSE_WIDTH = 'max-w-[70ch]'
