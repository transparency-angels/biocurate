import { Activity, House, ListOrdered, ScrollText, type LucideIcon } from 'lucide-react'
import { DEMO_OVERVIEW_PATH, DEMO_PROGRESS_PATH, DEMO_RESULTS_PATH } from '@/features/research/demoQuestion'

export interface NavDestination {
  label: string
  to: string
  icon: LucideIcon
  /** Small tag shown after the label, e.g. to mark demo content */
  tag?: string
  /** Pattern that marks the item active, when it covers more than its own path */
  activePattern?: string
}

export const NAV_DESTINATIONS: NavDestination[] = [
  { label: 'Home', to: '/', icon: House },
  {
    label: 'Research progress',
    to: DEMO_PROGRESS_PATH,
    icon: Activity,
    tag: 'Demo',
    activePattern: '/research/:sessionId/progress',
  },
  {
    label: 'Research results',
    to: DEMO_RESULTS_PATH,
    icon: ListOrdered,
    tag: 'Demo',
    activePattern: '/research/:sessionId/results',
  },
  {
    label: 'Research overview',
    to: DEMO_OVERVIEW_PATH,
    icon: ScrollText,
    tag: 'Demo',
    activePattern: '/research/:sessionId/overview',
  },
]
