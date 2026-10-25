import { cn } from '@/lib/utils'
import { AGENT_LABELS, actionLabel, type AgentProgress } from '@/services/eventAdapter'
import { AGENT_INFO } from './agentInfo'
import { StatusPill } from './StatusPill'
import { AGENT_STATUS } from './statusLabels'

function currentWork(agent: AgentProgress, sessionEnded: boolean) {
  const action = actionLabel(agent.action)
  if (agent.activity === 'running') {
    const more = agent.runningCount > 1 ? ` (${agent.runningCount} tasks)` : ''
    return { text: `${action}${more}`, current: true }
  }
  if (action) return { text: `Last task: ${action}`, current: false }
  return {
    text: sessionEnded ? 'Not scheduled for this research' : 'Waiting for work',
    current: false,
  }
}

/** One agent: what it does, its latest status and how many tasks it has finished. */
export function AgentStatusCard({ agent, sessionEnded }: { agent: AgentProgress; sessionEnded: boolean }) {
  const { icon: Icon, description } = AGENT_INFO[agent.name]
  const status = sessionEnded && agent.activity === 'idle'
    ? { label: 'Not scheduled', tone: 'neutral' as const }
    : AGENT_STATUS[agent.activity]
  const work = currentWork(agent, sessionEnded)
  const name = AGENT_LABELS[agent.name]

  return (
    <li className="grid grid-cols-[1.125rem_minmax(0,1fr)] gap-x-3 px-5 py-4 sm:grid-cols-[1.125rem_minmax(0,1fr)_auto] sm:px-6">
      <Icon
        aria-hidden="true"
        strokeWidth={1.75}
        className={cn('mt-0.5 size-[1.125rem]', agent.activity === 'running' ? 'text-brand' : 'text-muted-foreground')}
      />

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <h3 className="text-[0.9375rem] leading-6 font-medium text-foreground">{name}</h3>
          <StatusPill tone={status.tone} className="sm:hidden">
            {status.label}
          </StatusPill>
        </div>
        <p className="text-[0.8125rem] leading-5 text-muted-foreground">{description}</p>
        <p className={cn('mt-2 text-sm leading-5', work.current ? 'text-foreground' : 'text-faint')}>
          <span className="sr-only">{work.current ? 'Current task: ' : ''}</span>
          {work.text}
        </p>
        {agent.lastError && (
          <p className="mt-1 text-[0.8125rem] leading-5 break-words text-destructive">{agent.lastError}</p>
        )}
        <p className="mt-1 text-xs leading-5 text-muted-foreground tabular-nums sm:hidden">
          {agent.completedCount} completed
          {agent.failedCount > 0 && ` · ${agent.failedCount} failed`}
        </p>
      </div>

      <div className="hidden flex-col items-end gap-1.5 sm:flex">
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
        <p className="text-xs leading-5 text-muted-foreground tabular-nums">
          {agent.completedCount} completed
          {agent.failedCount > 0 && <span className="text-destructive"> · {agent.failedCount} failed</span>}
        </p>
      </div>
    </li>
  )
}
