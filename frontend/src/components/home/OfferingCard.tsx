import { cn } from '@/lib/utils'
import { AGENT_LABELS } from '@/services/eventAdapter'
import type { Offering, OfferingAccent } from './offerings'

// Full class names, so Tailwind can find them at build time
const ACCENT_CLASSES: Record<OfferingAccent, { icon: string; hover: string }> = {
  blue: { icon: 'text-brand', hover: 'hover:border-brand/40' },
  teal: { icon: 'text-teal', hover: 'hover:border-teal/40' },
  amber: { icon: 'text-amber', hover: 'hover:border-amber/40' },
}

/** One stage of a research session. Informational: the card is not a control. */
export function OfferingCard({ offering }: { offering: Offering }) {
  const { title, description, icon: Icon, accent, agents } = offering
  const classes = ACCENT_CLASSES[accent]

  return (
    <li
      className={cn(
        'flex flex-col rounded-xl border border-border bg-card p-6 transition-colors duration-200 motion-reduce:transition-none',
        classes.hover,
      )}
    >
      <Icon aria-hidden="true" strokeWidth={1.75} className={cn('size-5', classes.icon)} />
      <h3 className="mt-5 text-[1.0625rem] leading-6 font-semibold tracking-[-0.01em] text-foreground">
        {title}
      </h3>
      <p className="mt-2 text-[0.9375rem] leading-6 text-muted-foreground">{description}</p>

      <p className="mt-auto pt-6 text-[0.8125rem] leading-5 text-faint">
        {agents.map((agent) => AGENT_LABELS[agent]).join(' and ')} agents
      </p>
    </li>
  )
}
