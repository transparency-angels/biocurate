import { Link, useLocation } from 'react-router'
import { cn } from '@/lib/utils'

interface ResearchViewSwitchProps {
  sessionId: string
}

/**
 * Moves between the two views of one research session: the ranked hypotheses, and the
 * final synthesis. Both are links, so each view keeps its own URL and the browser's back
 * button behaves.
 */
export function ResearchViewSwitch({ sessionId }: ResearchViewSwitchProps) {
  const { pathname } = useLocation()
  const views = [
    { label: 'Hypotheses', to: `/research/${sessionId}/results` },
    { label: 'Research overview', to: `/research/${sessionId}/overview` },
  ]

  return (
    <nav aria-label="Research views">
      <ul className="flex gap-1 rounded-full border border-border bg-card p-1">
        {views.map((view) => {
          const active = pathname === view.to
          return (
            <li key={view.to}>
              <Link
                to={view.to}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex h-9 items-center rounded-full px-4 text-sm whitespace-nowrap transition-colors outline-none',
                  'focus-visible:ring-3 focus-visible:ring-ring/50',
                  active
                    ? 'bg-secondary font-medium text-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {view.label}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
