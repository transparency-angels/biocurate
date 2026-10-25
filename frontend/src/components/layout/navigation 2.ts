import { House, type LucideIcon } from 'lucide-react'

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
]
