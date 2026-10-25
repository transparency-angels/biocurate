import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { AgentWorkflow } from '@/components/progress/AgentWorkflow'
import { LiveHypotheses } from '@/components/progress/LiveHypotheses'
import { ResearchActivity } from '@/components/progress/ResearchActivity'
import { ResearchControls } from '@/components/progress/ResearchControls'
import { ResearchSessionHeader } from '@/components/progress/ResearchSessionHeader'
import { PHASE_STATUS } from '@/components/progress/statusLabels'
import { Button } from '@/components/ui/button'
import { useResearchProgress } from '@/hooks/useResearchProgress'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { getProgressSnapshot, getResearch, getSession, sessionAction, type SessionSnapshot } from '@/services/api'
import type { ProgressSnapshot } from '@/services/eventAdapter'
import { isTerminal } from '@/services/eventAdapter'
import { createSseEventSource } from '@/services/researchEventSource'
import type { ResearchSessionControls } from '@/services/researchEventSource'
import { NotFoundPage } from './NotFoundPage'
import type { ResearchSession } from '@/types/research'

function TitleRow({ action }: { action?: ReactNode }) {
  return <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4"><div className="min-w-0"><h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Research progress</h1><p className="mt-1 max-w-[42rem] text-sm leading-6 text-muted-foreground">Live updates from your research session.</p></div>{action}</div>
}

export function ResearchProgress() {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [research, setResearch] = useState<ResearchSession | null>(null)
  const [progressSnapshot, setProgressSnapshot] = useState<ProgressSnapshot | undefined>()
  const [error, setError] = useState<string | null>(null)
  const source = useMemo(() => createSseEventSource(sessionId), [sessionId])
  const snapshotStatus = session?.status
  const { progress, connectionLost, events } = useResearchProgress(source, { snapshotStatus, snapshot: progressSnapshot })
  const controls = useMemo<ResearchSessionControls>(() => ({
    pause: () => void sessionAction(sessionId, 'pause').catch((e) => setError(e.message)),
    resume: () => void sessionAction(sessionId, 'resume').catch((e) => setError(e.message)),
    abort: () => void sessionAction(sessionId, 'abort').catch((e) => setError(e.message)),
  }), [sessionId])

  const refresh = useCallback(() => {
    void getSession(sessionId).then(setSession).catch((e: Error) => setError(e.message))
    void getProgressSnapshot(sessionId).then(setProgressSnapshot).catch(() => undefined)
  }, [sessionId])
  const refreshResearch = useCallback(() => getResearch(sessionId, true).then(setResearch).catch(() => undefined), [sessionId])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(timer)
  }, [refresh])
  useEffect(() => {
    void refreshResearch()
    if (session && session.status !== 'running') return
    const timer = window.setInterval(() => void refreshResearch(), 2500)
    return () => window.clearInterval(timer)
  }, [refreshResearch, session?.status])
  const lastEventKey = events.at(-1)?.key
  const handledEventKey = useRef<string | undefined>(undefined)
  useEffect(() => {
    const event = events.at(-1)
    if (!event || event.key === handledEventKey.current) return
    handledEventKey.current = event.key
    const generatedHypothesis = event.name === 'task_completed' && !event.unknown && event.payload.kind === 'hypothesis_created'
    const timelineHypothesis = event.unknown && event.name === 'timeline_message' && event.payload.kind === 'hypothesis_created'
    if (generatedHypothesis || timelineHypothesis) void refreshResearch()
  }, [lastEventKey, events, refreshResearch])
  useDocumentTitle('Research progress')

  if (error && !session) return <NotFoundPage title="Could not load this session" message={error} />
  if (!session) return <div className="mx-auto w-full max-w-[76rem] px-4 py-10 text-sm text-muted-foreground">Loading research session…</div>
  const finished = isTerminal(progress.phase)

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <TitleRow action={finished ? <Button asChild className="h-11 gap-2 rounded-full px-4 sm:h-9"><Link to={`/research/${sessionId}/results`}>View results<ArrowRight aria-hidden="true" /></Link></Button> : undefined} />
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {connectionLost && <p role="status" className="mt-3 text-sm text-muted-foreground">Reconnecting to the live event stream…</p>}
      <p role="status" className="sr-only">Session status: {PHASE_STATUS[progress.phase].label}</p>
      <div className="mt-6"><ResearchSessionHeader question={session.research_goal} progress={progress}><ResearchControls phase={progress.phase} started={progress.startedAt !== null} controls={controls} /></ResearchSessionHeader></div>
      <LiveHypotheses hypotheses={research?.hypotheses ?? []} sessionId={sessionId} status={session.status} />
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-stretch"><AgentWorkflow progress={progress} /><div className="relative min-h-[24rem] max-lg:h-[28rem]"><ResearchActivity entries={progress.entries} className="lg:absolute lg:inset-0 max-lg:h-full" /></div></div>
    </div>
  )
}
