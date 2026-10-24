import { cn } from '@/lib/utils'
import type { ActivityTone } from '@/services/eventAdapter'
import { TONE_CLASSES } from './statusLabels'

interface StatusPillProps {
  tone: ActivityTone
  children: string
  className?: string
}

/** A status in words with a coloured dot, so the colour is never the only signal. */
export function StatusPill({ tone, children, className }: StatusPillProps) {
  const classes = TONE_CLASSES[tone]
  return (
    <span
      className={cn(
        'inline-flex h-6 flex-none items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap',
        classes.pill,
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn('size-1.5 rounded-full', classes.dot, tone === 'running' && 'motion-safe:animate-pulse')}
      />
      {children}
    </span>
  )
}
