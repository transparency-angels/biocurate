import { useState } from 'react'
import { Outlet } from 'react-router'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

const COLLAPSED_KEY = 'biocurate:sidebar-collapsed'

// A saved choice wins; otherwise the sidebar starts as an icon rail on tablets
function initialCollapsed() {
  try {
    const saved = localStorage.getItem(COLLAPSED_KEY)
    if (saved !== null) return saved === 'true'
  } catch {
    // Storage blocked; fall through to the width-based default
  }
  return window.matchMedia('(max-width: 63.99rem)').matches
}

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(initialCollapsed)

  function toggleCollapsed() {
    const next = !collapsed
    setCollapsed(next)
    try {
      localStorage.setItem(COLLAPSED_KEY, String(next))
    } catch {
      // The choice simply won't persist
    }
  }

  return (
    <div className="flex min-h-dvh bg-background">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main id="main" tabIndex={-1} className="flex min-w-0 flex-1 flex-col outline-none">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
