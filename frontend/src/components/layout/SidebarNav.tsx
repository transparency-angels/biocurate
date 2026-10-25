import { useEffect, useRef, useState } from 'react'
import { Link, matchPath, useLocation, useNavigate, useParams } from 'react-router'
import { Activity, ChartColumn, ChevronRight, ListOrdered, MessageCircle, MoreHorizontal, Pin, ScrollText, SquarePen, Trash2 } from 'lucide-react'
import { useNewResearch } from '@/features/research/useNewResearch'
import { clearCurrentSession } from '@/features/research/currentSession'
import { cn } from '@/lib/utils'
import { deleteResearchSession, getResearchSessions, type ResearchSessionSummary } from '@/services/api'
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
  const navigate = useNavigate()
  const { sessionId } = useParams()
  const [sessions, setSessions] = useState<ResearchSessionSummary[]>([])
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try {
      const parsed: unknown = JSON.parse(localStorage.getItem('biocurate:pinned-researches') ?? '[]')
      return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : []
    } catch { return [] }
  })
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    const refresh = () => void getResearchSessions().then((result) => { if (active) setSessions(result.sessions) }).catch(() => undefined)
    refresh()
    const timer = window.setInterval(refresh, 12000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const startNewResearch = useNewResearch()

  function togglePinned(id: string) {
    setPinnedIds((current) => {
      const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
      try { localStorage.setItem('biocurate:pinned-researches', JSON.stringify(next)) } catch { /* Pinning remains available for this view. */ }
      return next
    })
  }

  async function deleteResearch(session: ResearchSessionSummary) {
    if (session.status === 'running' || session.status === 'paused') return
    if (!window.confirm(`Delete this research permanently? Its hypotheses, conversation, files, and results will be removed.\n\n${session.research_goal}`)) return
    setDeletingId(session.id)
    setActionError(null)
    try {
      await deleteResearchSession(session.id)
      setSessions((current) => current.filter((item) => item.id !== session.id))
      setPinnedIds((current) => {
        const next = current.filter((id) => id !== session.id)
        try { localStorage.setItem('biocurate:pinned-researches', JSON.stringify(next)) } catch { /* The server deletion already succeeded. */ }
        return next
      })
      if (session.id === sessionId) {
        clearCurrentSession()
        navigate('/')
      }
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'Could not delete this research.')
    } finally {
      setDeletingId(null)
    }
  }

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

      <div className="my-3 border-t border-border" />

      {!collapsed && <h2 className="mb-2 px-2.5 text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-faint">Researches</h2>}
      {actionError && !collapsed && <p role="alert" className="mb-2 px-2.5 text-xs text-destructive">{actionError}</p>}
      {sessions.length === 0 ? (
        !collapsed && <p className="px-2.5 py-2 text-xs leading-5 text-muted-foreground">Your research sessions will appear here.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {[...sessions].sort((a, b) => Number(pinnedIds.includes(b.id)) - Number(pinnedIds.includes(a.id))).map((session) => {
            const active = session.id === sessionId
            return (
              <li key={session.id}>
                <div className="flex items-start gap-0.5">
                  <Link
                    to={`/research/${session.id}/chat`}
                    aria-current={active && pathname.endsWith('/chat') ? 'page' : undefined}
                    title={collapsed ? session.research_goal : undefined}
                    onClick={onNavigate}
                    className={cn(itemClass(active, collapsed), 'min-h-10 h-auto min-w-0 flex-1 py-2.5')}
                  >
                    <MessageCircle aria-hidden="true" className="size-[1.05rem] shrink-0" strokeWidth={1.75} />
                    <span className={cn('min-w-0 flex-1 truncate text-left leading-5', collapsed && 'sr-only')}>{session.research_goal}</span>
                    {pinnedIds.includes(session.id) && !collapsed && <Pin aria-label="Pinned research" className="size-3.5 shrink-0 text-brand" />}
                    {!collapsed && <span className="sr-only">{session.status}</span>}
                  </Link>
                  {!collapsed && <ResearchActions
                    pinned={pinnedIds.includes(session.id)}
                    canDelete={session.status !== 'running' && session.status !== 'paused'}
                    deleting={deletingId === session.id}
                    onTogglePin={() => togglePinned(session.id)}
                    onDelete={() => void deleteResearch(session)}
                  />}
                </div>
                {active && !collapsed && (
                  <ul className="ml-3 mt-1 flex flex-col gap-0.5 border-l border-border pl-2">
                    {[
                      { label: 'Progress', suffix: 'progress', icon: Activity },
                      { label: 'Results', suffix: 'results', icon: ListOrdered },
                      { label: 'Dataset', suffix: 'data', icon: ChartColumn },
                      { label: 'Overview', suffix: 'overview', icon: ScrollText },
                    ].map((item) => {
                      const to = `/research/${session.id}/${item.suffix}`
                      const selected = matchPath(`/research/:sessionId/${item.suffix}`, pathname) !== null
                      const Icon = item.icon
                      return <li key={item.suffix}><Link to={to} onClick={onNavigate} aria-current={selected ? 'page' : undefined} className={cn(itemClass(selected, false), 'h-8 px-2 text-xs')}><Icon aria-hidden="true" className="size-3.5 shrink-0" /><span>{item.label}</span><ChevronRight aria-hidden="true" className="ml-auto size-3 text-faint" /></Link></li>
                    })}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}

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

function ResearchActions({ pinned, canDelete, deleting, onTogglePin, onDelete }: {
  pinned: boolean
  canDelete: boolean
  deleting: boolean
  onTogglePin: () => void
  onDelete: () => void
}) {
  const menu = useRef<HTMLDetailsElement>(null)
  const close = () => { if (menu.current) menu.current.open = false }
  return (
    <details ref={menu} className="group relative shrink-0">
      <summary aria-label="Research actions" className="flex size-9 cursor-pointer list-none items-center justify-center rounded-lg text-muted-foreground outline-none hover:bg-secondary hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        <MoreHorizontal aria-hidden="true" className="size-4" />
      </summary>
      <div className="absolute right-0 top-10 z-30 w-48 rounded-xl border border-border bg-card p-1.5 shadow-lg">
        <button type="button" onClick={() => { onTogglePin(); close() }} className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm text-foreground hover:bg-secondary">
          <Pin aria-hidden="true" className="size-4 text-muted-foreground" />{pinned ? 'Unpin research' : 'Pin research'}
        </button>
        <button type="button" disabled={!canDelete || deleting} title={!canDelete ? 'Stop this research before deleting it.' : undefined} onClick={() => { close(); onDelete() }} className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50">
          <Trash2 aria-hidden="true" className="size-4" />{deleting ? 'Deleting…' : canDelete ? 'Delete research' : 'Stop before deleting'}
        </button>
      </div>
    </details>
  )
}
