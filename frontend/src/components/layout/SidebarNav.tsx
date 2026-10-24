import { Link, matchPath, useLocation } from 'react-router'
import { SquarePen } from 'lucide-react'
import { useNewResearch } from '@/features/research/useNewResearch'
import { cn } from '@/lib/utils'
import { NAV_DESTINATIONS } from './navigation'

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
  const startNewResearch = useNewResearch()

  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-0.5">
        {NAV_DESTINATIONS.map((item) => {
          const active = item.activePattern
            ? matchPath(item.activePattern, pathname) !== null
            : pathname === item.to
          const Icon = item.icon
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                aria-current={active ? 'page' : undefined}
                title={collapsed ? [item.label, item.tag && `(${item.tag.toLowerCase()})`].filter(Boolean).join(' ') : undefined}
                onClick={onNavigate}
                className={itemClass(active, collapsed)}
              >
                <Icon aria-hidden="true" className="size-[1.125rem] shrink-0" strokeWidth={1.75} />
                <span className={cn('truncate', collapsed && 'sr-only')}>{item.label}</span>
                {/* Quiet by design: the badge marks demo content without competing with the label */}
                {item.tag && (
                  <span
                    className={cn(
                      'ml-auto flex-none text-[0.6875rem] leading-4 font-normal text-faint',
                      collapsed && 'sr-only',
                    )}
                  >
                    {item.tag}
                  </span>
                )}
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
