import { Link, useLocation } from 'react-router'
import { cn } from '@/lib/utils'

interface ResearchViewSwitchProps {
  sessionId: string
}

/**
 * Keeps conversation, progress and saved research views together under one session.
 */
export function ResearchViewSwitch({ sessionId }: ResearchViewSwitchProps) {
  const { pathname } = useLocation()
  const views = [
    { label: 'Conversation', to: `/research/${sessionId}/chat` },
    { label: 'Progress', to: `/research/${sessionId}/progress` },
    { label: 'Hypotheses', to: `/research/${sessionId}/results` },
    { label: 'Dataset analysis', to: `/research/${sessionId}/data` },
    { label: 'Sources', to: `/research/${sessionId}/sources` },
    { label: 'Research overview', to: `/research/${sessionId}/overview` },
  ]

  return (
    <nav aria-label="Research views" className="w-full overflow-x-auto">
      <ul className="flex w-max min-w-full flex-nowrap gap-1 rounded-2xl border border-border bg-card p-1">
        {views.map((view) => {
          const active = pathname === view.to
          return (
            <li key={view.to}>
              <Link
                to={view.to}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex h-9 items-center rounded-full px-3 text-xs whitespace-nowrap transition-colors outline-none sm:px-4 sm:text-sm',
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
