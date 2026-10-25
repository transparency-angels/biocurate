import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowRight, CheckCircle2, CircleAlert, Clock3, FlaskConical, LoaderCircle } from 'lucide-react'
import { ResearchChat } from '@/components/research/ResearchChat'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { Button } from '@/components/ui/button'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { getCachedProgressSnapshot, getCachedResearch, getCachedSession, getProgressSnapshot, getResearch, getSession, type SessionSnapshot } from '@/services/api'
import type { ProgressSnapshot } from '@/services/eventAdapter'
import type { ResearchSession } from '@/types/research'
import { NotFoundPage } from './NotFoundPage'

const STATUS: Record<SessionSnapshot['status'], { label: string; color: string }> = {
  running: { label: 'In progress', color: 'bg-brand/10 text-brand' },
  paused: { label: 'Paused', color: 'bg-amber/10 text-amber' },
  done: { label: 'Complete', color: 'bg-success/10 text-success' },
  failed: { label: 'Stopped with errors', color: 'bg-destructive/10 text-destructive' },
  aborted: { label: 'Stopped', color: 'bg-muted text-muted-foreground' },
}

export function ResearchWorkspace() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<SessionSnapshot | null>(() => getCachedSession(sessionId) ?? null)
  const [research, setResearch] = useState<ResearchSession | null>(() => getCachedResearch(sessionId, true) ?? null)
  const [progress, setProgress] = useState<ProgressSnapshot | null>(() => getCachedProgressSnapshot(sessionId) ?? null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(() => !getCachedSession(sessionId) || !getCachedResearch(sessionId, true) || !getCachedProgressSnapshot(sessionId))

  const refresh = useCallback(() => {
    void Promise.all([getSession(sessionId), getResearch(sessionId, true), getProgressSnapshot(sessionId)])
      .then(([stored, results, snapshot]) => { setSession(stored); setResearch(results); setProgress(snapshot); setError(null) })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false))
  }, [sessionId])
  const sessionStatus = session?.status

  useEffect(() => {
    refresh()
    if (sessionStatus && sessionStatus !== 'running' && sessionStatus !== 'paused') return
    const timer = window.setInterval(refresh, 8000)
    return () => window.clearInterval(timer)
  }, [refresh, sessionStatus])
  useDocumentTitle('Research conversation')

  if (error && !session) return <NotFoundPage title="Research unavailable" message={error} />
  if (loading || !session || !research || !progress) return <div className="mx-auto w-full max-w-[76rem] px-4 py-10 text-sm text-muted-foreground">Opening your research workspace…</div>

  const status = STATUS[session.status]
  const available = research.hypotheses.filter((hypothesis) => hypothesis.state === 'in_tournament' || hypothesis.state === 'pinned' || (hypothesis.state === 'reviewed' && !research.hypotheses.some((h) => h.state === 'in_tournament')))
  const runningAgents = progress.agents.filter((agent) => agent.activity === 'running')
  const failedAgents = progress.agents.filter((agent) => agent.activity === 'failed')

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />
      <div className="mt-5">
        <div className="min-w-0 max-w-[60rem]">
          <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${status.color}`}>{status.label}</span><span className="text-xs text-muted-foreground">Research workspace</span></div>
          <h1 className="mt-3 break-words font-serif text-2xl leading-9 text-foreground sm:text-3xl">{session.research_goal}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">Discuss your findings, keep track of what the agents have done, and return to the evidence from one place.</p>
        </div>
      </div>
      {error && <p role="status" className="mt-4 text-xs text-muted-foreground">Research details could not be refreshed. Your conversation is still available.</p>}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(18rem,.65fr)] xl:gap-6">
        <ResearchChat key={sessionId} sessionId={sessionId} sessionStatus={session.status} />

        <aside aria-label="Research summary" className="space-y-4">
          <section className="rounded-2xl border border-border bg-card p-5 sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div><p className="text-xs font-medium uppercase tracking-[0.11em] text-muted-foreground">Research at a glance</p><h2 className="mt-1 text-base font-semibold text-foreground">Session snapshot</h2></div>
              <FlaskConical aria-hidden="true" className="size-5 text-brand" />
            </div>
            <dl className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-muted/50 p-3"><dt className="text-xs text-muted-foreground">Hypotheses</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{research.hypotheses.length}</dd></div>
              <div className="rounded-xl bg-muted/50 p-3"><dt className="text-xs text-muted-foreground">Tasks completed</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{progress.completed_tasks}</dd></div>
            </dl>
            {runningAgents.length > 0 ? <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><LoaderCircle aria-hidden="true" className="size-3.5 animate-spin text-brand" />{runningAgents.map((agent) => agent.name.replace('_', ' ')).join(', ')} working now</p> : failedAgents.length > 0 ? <p className="mt-4 flex items-center gap-2 text-xs text-amber"><CircleAlert aria-hidden="true" className="size-3.5" />{failedAgents.length} agent {failedAgents.length === 1 ? 'has' : 'have'} a task to review</p> : <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><CheckCircle2 aria-hidden="true" className="size-3.5 text-success" />Latest saved state is up to date</p>}
            <Link to={`/research/${sessionId}/progress`} className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">Open research progress<ArrowRight aria-hidden="true" className="size-3.5" /></Link>
          </section>

          <section className="rounded-2xl border border-border bg-card p-5 sm:p-6">
            <div className="flex items-baseline justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-[0.11em] text-muted-foreground">Saved findings</p><h2 className="mt-1 text-base font-semibold text-foreground">Leading hypotheses</h2></div><span className="text-xs tabular-nums text-muted-foreground">{available.length}</span></div>
            {available.length > 0 ? <ol className="mt-4 divide-y divide-border">{available.slice(0, 3).map((hypothesis, index) => <li key={hypothesis.id} className="py-3 first:pt-0 last:pb-0"><Link to={`/research/${sessionId}/results?hypothesis=${encodeURIComponent(hypothesis.id)}`} className="group flex items-start gap-3 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"><span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-semibold tabular-nums text-brand">{index + 1}</span><span className="min-w-0"><span className="block text-sm font-medium leading-5 text-foreground group-hover:text-brand">{hypothesis.title}</span><span className="mt-1 line-clamp-2 block text-xs leading-5 text-muted-foreground">{hypothesis.summary}</span></span></Link></li>)}</ol> : <p className="mt-3 text-sm leading-6 text-muted-foreground">Hypotheses will appear here when they have been reviewed and saved.</p>}
            <Button asChild variant="outline" className="mt-5 w-full justify-between rounded-xl"><Link to={`/research/${sessionId}/results`}>Explore research results<ArrowRight aria-hidden="true" className="size-4" /></Link></Button>
          </section>

          <section className="rounded-2xl border border-border bg-card p-5 sm:p-6">
            <div className="flex items-center gap-2"><Clock3 aria-hidden="true" className="size-4 text-brand" /><h2 className="text-sm font-semibold text-foreground">Continue exploring</h2></div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to={`/research/${sessionId}/data`} className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:border-brand/30 hover:text-foreground">Dataset analysis</Link>
              <Link to={`/research/${sessionId}/overview`} className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:border-brand/30 hover:text-foreground">Research overview</Link>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
