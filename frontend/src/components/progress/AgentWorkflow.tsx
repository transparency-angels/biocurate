import { useId } from 'react'
import type { ResearchProgress } from '@/services/eventAdapter'
import { AgentStatusCard } from './AgentStatusCard'

/** The six Co-Scientist agents. Shown as peers, not steps: the supervisor runs them in any order. */
export function AgentWorkflow({ progress }: { progress: ResearchProgress }) {
  const headingId = useId()
  const { completedTasks, failedTasks, unattributedResults } = progress
  const sessionEnded = ['completed', 'failed', 'aborted'].includes(progress.phase)

  return (
    <section aria-labelledby={headingId} className="min-w-0 rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 pt-4 pb-3 sm:px-6">
        <h2 id={headingId} className="text-base font-semibold text-foreground">
          Agents
        </h2>
        <p className="text-[0.8125rem] text-muted-foreground tabular-nums">
          {completedTasks} {completedTasks === 1 ? 'task' : 'tasks'} completed
          {failedTasks > 0 && ` · ${failedTasks} failed`}
        </p>
        <p className="w-full text-[0.8125rem] leading-5 text-muted-foreground">
          Agents run repeatedly and in any order as the supervisor schedules work.
        </p>
      </div>

      <ul className="divide-y divide-border border-t border-border">
        {progress.agents.map((agent) => (
          <AgentStatusCard key={agent.name} agent={agent} sessionEnded={sessionEnded} />
        ))}
      </ul>

      {unattributedResults > 0 && (
        <p className="border-t border-border px-5 py-3 text-[0.8125rem] leading-5 text-muted-foreground sm:px-6">
          Task results without a matching start event: {unattributedResults}. Their agent is unknown, so
          they appear in the activity log only.
        </p>
      )}
    </section>
  )
}
