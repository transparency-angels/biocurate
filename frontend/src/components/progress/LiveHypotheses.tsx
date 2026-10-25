import { Link } from 'react-router'
import { ArrowRight, FlaskConical } from 'lucide-react'
import type { Hypothesis } from '@/types/research'
import type { SessionSnapshot } from '@/services/api'

interface LiveHypothesesProps {
  hypotheses: Hypothesis[]
  sessionId: string
  status: SessionSnapshot['status']
}

const stateLabel: Record<NonNullable<Hypothesis['state']>, string> = {
  draft: 'In review',
  reviewed: 'Reviewed',
  in_tournament: 'Ranked',
  pinned: 'Pinned',
  rejected: 'Rejected',
  quarantined: 'Under review',
  retired: 'Archived',
}

export function LiveHypotheses({ hypotheses, sessionId, status }: LiveHypothesesProps) {
  const recent = [...hypotheses]
    .sort((a, b) => Date.parse(b.createdAt ?? '') - Date.parse(a.createdAt ?? ''))
    .slice(0, 4)
  const rankedCount = hypotheses.filter((hypothesis) => hypothesis.state === 'in_tournament' || hypothesis.state === 'pinned').length

  return (
    <section aria-labelledby="live-hypotheses-title" className="mt-6 rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
        <div className="flex items-center gap-2.5">
          <FlaskConical aria-hidden="true" className="size-4 text-brand" />
          <div>
            <h2 id="live-hypotheses-title" className="text-sm font-semibold text-foreground">Hypotheses so far</h2>
            <p className="mt-0.5 text-xs text-muted-foreground" aria-live="polite">
              {hypotheses.length === 0 ? 'Ideas will appear here as they are generated.' : `${hypotheses.length} generated · ${rankedCount} ranked`}
            </p>
          </div>
        </div>
        {rankedCount > 0 && <Link to={`/research/${sessionId}/results`} className="inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">Open ranked results<ArrowRight aria-hidden="true" className="size-3.5" /></Link>}
      </div>

      {recent.length > 0 ? (
        <ol className="divide-y divide-border">
          {recent.map((hypothesis) => {
            const status = hypothesis.state ? stateLabel[hypothesis.state] : 'Generated'
            return (
              <li key={hypothesis.id} className="px-5 py-4 sm:px-6">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h3 className="text-sm font-medium leading-6 text-foreground">{hypothesis.title}</h3>
                  <span className="shrink-0 text-xs text-muted-foreground">{status}</span>
                </div>
                <p className="mt-1 max-w-[76ch] whitespace-pre-line text-sm leading-6 text-muted-foreground">{hypothesis.summary}</p>
                {(hypothesis.state === 'in_tournament' || hypothesis.state === 'pinned' || (hypothesis.state === 'reviewed' && rankedCount === 0)) && <Link to={`/research/${sessionId}/results?hypothesis=${encodeURIComponent(hypothesis.id)}`} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">Open this hypothesis<ArrowRight aria-hidden="true" className="size-3.5" /></Link>}
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="px-5 py-5 text-sm text-muted-foreground sm:px-6">
          {status === 'done' ? 'The session finished without saving a hypothesis.' : status === 'failed' ? 'The session stopped before a hypothesis was saved. Check the activity log for details.' : status === 'aborted' ? 'The session was stopped before a hypothesis was saved.' : status === 'paused' ? 'The session is paused. Resume it to continue developing hypotheses.' : 'The first ideas are still being developed. This list updates as soon as they are saved.'}
        </p>
      )}
    </section>
  )
}
