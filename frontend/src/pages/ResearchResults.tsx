import { useCallback, useEffect, useId, useState } from 'react'
import { useLocation, useParams } from 'react-router'
import { HypothesisList } from '@/components/HypothesisList'
import { HypothesisTabs, type HypothesisTab } from '@/components/HypothesisTabs'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { getCachedResearch, getResearch, getSession, type SessionSnapshot } from '@/services/api'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import type { ResearchSession } from '@/types/research'
import { NotFoundPage } from './NotFoundPage'

export function ResearchResults() {
  const { sessionId = '' } = useParams()
  const location = useLocation()
  const [session, setSession] = useState<ResearchSession | null>(() => getCachedResearch(sessionId) ?? null)
  const [question, setQuestion] = useState('')
  const [sessionStatus, setSessionStatus] = useState<SessionSnapshot['status'] | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activeTab, setActiveTab] = useState<HypothesisTab>('evaluation')
  const detailsId = useId()
  const questionHeadingId = useId()

  const refresh = useCallback(() => Promise.all([getResearch(sessionId), getSession(sessionId)])
    .then(([research, stored]) => {
      setSession(research)
      setQuestion(stored.research_goal)
      setSessionStatus(stored.status)
      setUpdatedAt(Date.now())
      setError(null)
    })
    .catch((e: Error) => setError(e.message)), [sessionId])
  useEffect(() => {
    let active = true
    const load = () => { if (active) void refresh() }
    load()
    const timer = sessionStatus === 'running' ? window.setInterval(load, 3000) : undefined
    return () => { active = false; if (timer !== undefined) window.clearInterval(timer) }
  }, [refresh, sessionStatus])
  useDocumentTitle(session ? 'Research results' : 'Research results')

  if (error && !session) return <NotFoundPage title="Results unavailable" message={error} />
  if (!session) return <div className="mx-auto w-full max-w-[76rem] px-4 py-10 text-sm text-muted-foreground">Loading research results…</div>
  if (session.hypotheses.length === 0) return <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8"><ResearchViewSwitch sessionId={sessionId} /><h1 className="mt-5 text-2xl font-semibold tracking-[-0.01em] text-foreground">Research results</h1><div className="mt-6 rounded-xl border border-border bg-card p-5"><p className="text-sm font-medium text-foreground">No ranked hypotheses yet</p><p className="mt-1 text-sm text-muted-foreground">{sessionStatus === 'done' ? 'This session finished without a ranked hypothesis.' : 'This page updates as hypotheses are reviewed and ranked.'}</p>{error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}</div></div>

  const requestedId = new URLSearchParams(location.search).get('hypothesis')
  const selected = session.hypotheses.find((h) => h.id === selectedId) ?? session.hypotheses.find((h) => h.id === requestedId) ?? session.hypotheses[0]
  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />
      <div className="mt-5"><h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Research results</h1>{sessionStatus === 'running' && <p className="mt-1 text-sm text-muted-foreground">Updating as hypotheses are reviewed and ranked.</p>}</div>
      {error && <p role="status" className="mt-3 text-sm text-muted-foreground">Could not refresh just now. Showing the latest saved results.</p>}
      <section aria-labelledby={questionHeadingId} className="mt-6 rounded-xl border border-border bg-card px-5 py-4 sm:px-6"><h2 id={questionHeadingId} className="text-xs text-muted-foreground">Your research question</h2><p className="mt-1.5 break-words whitespace-pre-line font-serif text-[1.0625rem] leading-7 text-foreground">{question}</p></section>
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:items-start lg:gap-8"><HypothesisList hypotheses={session.hypotheses} selectedId={selected.id} detailsId={detailsId} onSelect={setSelectedId} /><HypothesisTabs id={detailsId} sessionId={sessionId} hypothesis={selected} total={session.hypotheses.length} activeTab={activeTab} onTabChange={setActiveTab} /></div>
      {updatedAt !== null && sessionStatus === 'running' && <p className="mt-4 text-right text-xs text-faint">Updated {new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' }).format(updatedAt)}</p>}
    </div>
  )
}
