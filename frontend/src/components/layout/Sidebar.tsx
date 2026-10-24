import { Link } from 'react-router'
import { FlaskConical, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { BioCurateWordmark } from '@/components/brand/BioCurateWordmark'
import { cn } from '@/lib/utils'
import { SidebarNav } from './SidebarNav'

interface SidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
}

/** The permanent sidebar from tablet width up. Phones use MobileNav instead. */
export function Sidebar({ collapsed, onToggleCollapsed }: SidebarProps) {
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose
  const toggleLabel = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-background md:flex',
        'motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out',
        collapsed ? 'w-16' : 'w-62',
      )}
    >
      <div className={cn('flex h-14 shrink-0 items-center', collapsed ? 'justify-center' : 'px-5')}>
        <Link
          to="/"
          aria-label="BioCurate home"
          className="rounded-md text-[1.0625rem] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {collapsed ? (
            <FlaskConical aria-hidden="true" className="size-5 text-brand" strokeWidth={1.75} />
          ) : (
            <BioCurateWordmark />
          )}
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2">
        <SidebarNav collapsed={collapsed} />
      </div>

      <div className={cn('shrink-0 px-3 pb-4', collapsed && 'flex justify-center')}>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={toggleLabel}
          title={toggleLabel}
          className={cn(
            'flex h-9 items-center gap-2.5 rounded-lg text-sm text-faint transition-colors outline-none',
            'hover:bg-secondary hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
            collapsed ? 'w-10 justify-center' : 'w-full px-2.5',
          )}
        >
          <ToggleIcon aria-hidden="true" className="size-[1.125rem] shrink-0" strokeWidth={1.75} />
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
