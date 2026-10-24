import { Link, useMatch } from 'react-router'
import { ChevronRight, SquarePen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useNewResearch } from '@/features/research/useNewResearch'
import { MobileNav } from './MobileNav'

function usePageTitle() {
  const isHome = useMatch('/') !== null
  const isProgress = useMatch('/research/:sessionId/progress') !== null
  const isResults = useMatch('/research/:sessionId/results') !== null
  const isOverview = useMatch('/research/:sessionId/overview') !== null
  const isResearch = isProgress || isResults || isOverview
  if (isHome) return { title: 'Home', isResearch, isHome }
  if (isProgress) return { title: 'Research progress', isResearch, isHome }
  if (isResults) return { title: 'Research results', isResearch, isHome }
  if (isOverview) return { title: 'Research overview', isResearch, isHome }
  return { title: 'Page not found', isResearch, isHome }
}

export function Header() {
  const { title, isResearch, isHome } = usePageTitle()
  const startNewResearch = useNewResearch()

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-4 sm:px-6 lg:px-8">
      <MobileNav />

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex items-center gap-1.5 text-sm">
          <li className={cn('flex items-center gap-1.5 max-md:hidden', isHome && 'hidden')}>
            <Link
              to="/"
              className="rounded-sm text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              BioCurate
            </Link>
            <ChevronRight aria-hidden="true" className="size-3.5 text-faint" />
          </li>
          <li className="min-w-0">
            {/* On the home page the sidebar already says where you are, so the title is phone-only */}
            <span
              aria-current="page"
              className={cn('block truncate font-medium text-foreground', isHome && 'md:hidden')}
            >
              {title}
            </span>
          </li>
        </ol>
      </nav>

      {isResearch && (
        <Button onClick={startNewResearch} className="h-9 gap-2 rounded-full px-3.5">
          <SquarePen aria-hidden="true" />
          New research
        </Button>
      )}
    </header>
  )
}
