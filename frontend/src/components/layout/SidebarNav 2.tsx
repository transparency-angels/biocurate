import { useEffect, useState } from 'react'
import { Link, matchPath, useLocation, useParams } from 'react-router'
import { Activity, ChartColumn, ListOrdered, ScrollText, SquarePen } from 'lucide-react'
import { useNewResearch } from '@/features/research/useNewResearch'
import { readCurrentSession, subscribeCurrentSession } from '@/features/research/currentSession'
import { cn } from '@/lib/utils'
import { NAV_DESTINATIONS, type NavDestination } from './navigation'

interface SidebarNavProps {
  collapsed?: boolean
  /** Called after any item is chosen, e.g. to close the mobile drawer */
  onNavigate?: () => void
}

const itemClass = (active: boolean, collapsed: boolean) =>
  cn(
    'flex h-11 w-full items-center gap-2.5 rounded-lg text-sm transition-colors outline-none md:h-9',
    'focus-visible:ring-3 focus-visible:ring-ring/50',
    collapsed ? 'justify-center px-0' : 'px-2.5',
    active
      ? 'bg-secondary font-medium text-foreground'
      : 'text-muted-foreground hover:bg-secondary/70 hover:text-foreground',
  )

export function SidebarNav({ collapsed = false, onNavigate }: SidebarNavProps) {
  const { pathname } = useLocation()
  const { sessionId } = useParams()
  const [currentSession, setCurrentSession] = useState(readCurrentSession)
  useEffect(() => subscribeCurrentSession(() => setCurrentSession(readCurrentSession())), [])
  const activeSessionId = sessionId ?? currentSession?.id
  const sessionItems: NavDestination[] = activeSessionId ? [
    { label: 'Research progress', to: `/research/${activeSessionId}/progress`, icon: Activity, activePattern: '/research/:sessionId/progress' },
    { label: 'Research results', to: `/research/${activeSessionId}/results`, icon: ListOrdered, activePattern: '/research/:sessionId/results' },
    { label: 'Dataset analysis', to: `/research/${activeSessionId}/data`, icon: ChartColumn, activePattern: '/research/:sessionId/data' },
    { label: 'Research overview', to: `/research/${activeSessionId}/overview`, icon: ScrollText, activePattern: '/research/:sessionId/overview' },
  ] : []
  const destinations = [...NAV_DESTINATIONS, ...sessionItems]
  const startNewResearch = useNewResearch()

  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-0.5">
        {destinations.map((item) => {
          const active = item.activePattern
            ? matchPath(item.activePattern, pathname) !== null
            : pathname === item.to
          const Icon = item.icon
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                aria-current={active ? 'page' : undefined}
                title={collapsed ? item.label : undefined}
                onClick={onNavigate}
                className={itemClass(active, collapsed)}
              >
                <Icon aria-hidden="true" className="size-[1.125rem] shrink-0" strokeWidth={1.75} />
                <span className={cn('truncate', collapsed && 'sr-only')}>{item.label}</span>
              </Link>
            </li>
          )
        })}
      </ul>

      <div role="presentation" className="my-3 border-t border-border" />

      <button
        type="button"
        title={collapsed ? 'New research' : undefined}
        onClick={() => {
          startNewResearch()
          onNavigate?.()
        }}
        className={itemClass(false, collapsed)}
      >
        <SquarePen aria-hidden="true" className="size-[1.125rem] shrink-0" strokeWidth={1.75} />
        <span className={cn(collapsed && 'sr-only')}>New research</span>
      </button>
    </nav>
  )
}
