import {
  AGENT_NAMES,
  KNOWN_EVENT_NAMES,
  type AgentName,
  type BackendSessionStatus,
  type KnownEventName,
  type ResearchEvent,
  type SseMessage,
  type StopReason,
  type TaskAction,
  type TaskResultKind,
} from '@/types/researchEvents'

// ----------------------------- parsing ----------------------------- //

type Json = Record<string, unknown>

const isRecord = (value: unknown): value is Json =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const str = (value: unknown) => (typeof value === 'string' ? value : null)
const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null)

function isKnownName(name: string): name is KnownEventName {
  return (KNOWN_EVENT_NAMES as readonly string[]).includes(name)
}

function isAgentName(value: unknown): value is AgentName {
  return typeof value === 'string' && (AGENT_NAMES as readonly string[]).includes(value)
}

/**
 * Checks the fields a known event cannot do without and fills the optional ones.
 * Returns null when a required field is missing, so the event is logged as unrecognised
 * instead of corrupting agent state.
 */
function normalisePayload(name: KnownEventName, raw: Json): Json | null {
  switch (name) {
    case 'session_started':
      return { goal: str(raw.goal) ?? '', n_initial: num(raw.n_initial), budget_usd: num(raw.budget_usd) }
    case 'task_started': {
      const taskId = str(raw.task_id)
      if (!taskId || !isAgentName(raw.agent)) return null
      return { task_id: taskId, agent: raw.agent, action: str(raw.action) ?? '', target: str(raw.target) }
    }
    case 'task_completed': {
      const taskId = str(raw.task_id)
      if (!taskId) return null
      const ids = Array.isArray(raw.follow_hypothesis_ids) ? raw.follow_hypothesis_ids.filter((id) => typeof id === 'string') : []
      return { task_id: taskId, kind: str(raw.kind) ?? '', follow_hypothesis_ids: ids }
    }
    case 'task_failed': {
      const taskId = str(raw.task_id)
      if (!taskId) return null
      return { task_id: taskId, err: str(raw.err) ?? '' }
    }
    case 'session_done':
      return { stop_reason: str(raw.stop_reason) }
    case 'human_feedback':
      return { kind: str(raw.kind) ?? '', target_id: str(raw.target_id), text: str(raw.text) ?? '' }
    case 'session_paused':
    case 'session_resumed':
    case 'session_aborted':
      return {}
  }
}

/**
 * Turns one SSE message into a normalised event, or null when its data is not JSON.
 *
 * The endpoint sends two shapes: replayed history as `{payload, ts}` and live bus events
 * as `{name, session_id, payload, ts_ms}`. Both are accepted.
 */
export function parseSseMessage(message: SseMessage): ResearchEvent | null {
  let data: unknown
  try {
    data = JSON.parse(message.data)
  } catch {
    return null
  }
  if (!isRecord(data)) return null

  const liveTs = num(data.ts_ms)
  const replayTs = num(data.ts)
  const ts = liveTs ?? replayTs
  if (ts === null) return null
  const origin = liveTs !== null ? 'live' : 'replay'

  // An unnamed SSE event arrives as "message"; live data also names itself
  const name = message.event && message.event !== 'message' ? message.event : (str(data.name) ?? 'message')
  const rawPayload = isRecord(data.payload) ? data.payload : {}

  const payload = isKnownName(name) ? normalisePayload(name, rawPayload) : null
  const key = `${ts}|${name}|${JSON.stringify(payload ?? rawPayload)}`

  if (payload === null) {
    return { name, unknown: true, payload: rawPayload, ts, origin, key }
  }
  return { name, payload, ts, origin, key } as ResearchEvent
}

// ----------------------------- de-duplication ----------------------------- //

/**
 * How far apart the replayed and live copies of one event can be stamped.
 * The backend writes the database row (`ts`) just before it publishes to the bus (`ts_ms`),
 * so the two copies differ by a few milliseconds. A retried task is seconds apart.
 */
const CROSS_ORIGIN_WINDOW_MS = 2000

const signature = (key: string) => key.slice(key.indexOf('|') + 1)

/**
 * Adds an event to a list kept in timestamp order, unless it is already there.
 *
 * The backend sends no event ids. A reconnect replays the last 25 events with their
 * original timestamps (caught by the exact key), and an event can arrive both as a replay
 * and live with slightly different timestamps (caught by the window).
 * Returns the same array when nothing changed, so React can skip the update.
 */
export function ingestEvent(events: ResearchEvent[], event: ResearchEvent): ResearchEvent[] {
  const sig = signature(event.key)
  const duplicate = events.some(
    (existing) =>
      existing.key === event.key ||
      (existing.origin !== event.origin &&
        Math.abs(existing.ts - event.ts) <= CROSS_ORIGIN_WINDOW_MS &&
        signature(existing.key) === sig),
  )
  if (duplicate) return events

  // Usually appended; replayed history can arrive older than events already shown
  let index = events.length
  while (index > 0 && events[index - 1].ts > event.ts) index--
  return [...events.slice(0, index), event, ...events.slice(index)]
}

// ----------------------------- state ----------------------------- //

/** The session as the dashboard shows it. "preparing" is a frontend state: see reduceEvents. */
export type SessionPhase = 'preparing' | 'running' | 'paused' | 'completed' | 'failed' | 'aborted'

export type AgentActivity = 'idle' | 'running' | 'completed' | 'failed'

export interface AgentProgress {
  name: AgentName
  activity: AgentActivity
  /** Tasks started and not yet reported finished */
  runningCount: number
  completedCount: number
  failedCount: number
  /** The action in progress, or the last one this agent ran */
  action: TaskAction | null
  lastError: string | null
}

export type ActivityTone = 'neutral' | 'running' | 'success' | 'error'

export interface ActivityEntry {
  key: string
  ts: number
  /** Readable event type, e.g. "Task started" */
  type: string
  agent: AgentName | null
  description: string
  error: string | null
  tone: ActivityTone
}

export interface ResearchProgress {
  phase: SessionPhase
  goal: string | null
  startedAt: number | null
  endedAt: number | null
  budgetUsd: number | null
  initialHypotheses: number | null
  stopReason: StopReason | null
  agents: AgentProgress[]
  completedTasks: number
  failedTasks: number
  /** Task results whose task_started was never received, so their agent is unknown */
  unattributedResults: number
  entries: ActivityEntry[]
}

const TERMINAL: SessionPhase[] = ['completed', 'failed', 'aborted']
export const isTerminal = (phase: SessionPhase) => TERMINAL.includes(phase)

export const AGENT_LABELS: Record<AgentName, string> = {
  generation: 'Generation',
  reflection: 'Reflection',
  ranking: 'Ranking',
  evolution: 'Evolution',
  proximity: 'Proximity',
  metareview: 'Meta-review',
}

export const ACTION_LABELS: Record<TaskAction, string> = {
  CreateInitialHypotheses: 'Creating an initial hypothesis',
  GenerateFromFeedback: 'Generating a hypothesis from feedback',
  DirectGeneration: 'Generating a hypothesis',
  ReviewHypothesis: 'Reviewing a hypothesis',
  AddToTournament: 'Entering a hypothesis into the ranking tournament',
  RunTournamentBatch: 'Comparing hypotheses in the tournament',
  EvolveTopHypotheses: 'Refining the top-ranked hypotheses',
  UpdateProximityGraph: 'Grouping similar hypotheses',
  GenerateSystemFeedback: 'Summarising patterns across reviews',
  GenerateFinalResearchOverview: 'Writing the final research overview',
}

export const STOP_REASON_LABELS: Record<StopReason, string> = {
  budget: 'Budget limit reached',
  wall_clock: 'Time limit reached',
  elo_stable: 'Rankings stopped changing',
  external: 'Stopped on request',
  idle: 'No further work to schedule',
}

export const actionLabel = (action: string | null) =>
  action ? (ACTION_LABELS[action as TaskAction] ?? action) : null

function resultLabel(kind: string, hypothesisIds: string[]) {
  switch (kind as TaskResultKind) {
    case 'hypothesis_created': {
      const n = hypothesisIds.length
      // The backend sends at most five ids
      if (n >= 5) return 'Five or more hypotheses created'
      return n === 1 ? 'Hypothesis created' : `${n} hypotheses created`
    }
    case 'review_completed':
      return 'Review completed'
    case 'added_to_tournament':
      return 'Hypothesis entered into the tournament'
    case 'tournament_match_complete':
      return 'Tournament comparison completed'
    case 'proximity_updated':
      return 'Similar hypotheses grouped'
    case 'evolution_completed':
      return 'Refinement completed'
    case 'system_feedback_generated':
      return 'Review summary written'
    case 'final_overview_generated':
      return 'Final research overview written'
    case 'noop':
      return 'Finished with nothing to do yet'
    default:
      return 'Task completed'
  }
}

interface TaskRecord {
  agent: AgentName
  action: string
  state: 'running' | 'completed' | 'failed'
}

interface AgentTally {
  completed: number
  failed: number
  lastAction: string | null
  lastOutcome: 'completed' | 'failed' | null
  lastError: string | null
}

export interface ReduceOptions {
  /**
   * Status from `GET /api/sessions/{id}`. The event stream never reports a failed session and
   * the replay omits pause, resume and abort, so a live integration should pass this through.
   */
  snapshotStatus?: BackendSessionStatus
}

/**
 * Folds an ordered event list into dashboard state. A pure function of the list, so
 * replayed or out-of-order events are handled by re-sorting rather than by patching state.
 *
 * Phases: "preparing" until the first task starts (the backend parses the goal into a plan
 * between session_started and the first task), then running / paused, and finally completed
 * or aborted from session_done. An agent that finishes a task stays available for more:
 * only session_done ends the session.
 */
export function reduceEvents(events: ResearchEvent[], options: ReduceOptions = {}): ResearchProgress {
  const tasks = new Map<string, TaskRecord>()
  const tallies = Object.fromEntries(
    AGENT_NAMES.map((name) => [name, { completed: 0, failed: 0, lastAction: null, lastOutcome: null, lastError: null }]),
  ) as Record<AgentName, AgentTally>

  let phase: SessionPhase = 'preparing'
  let anyTaskStarted = false
  let goal: string | null = null
  let startedAt: number | null = null
  let endedAt: number | null = null
  let budgetUsd: number | null = null
  let initialHypotheses: number | null = null
  let stopReason: StopReason | null = null
  let unattributedResults = 0
  const entries: ActivityEntry[] = []

  for (const event of events) {
    const base = { key: event.key, ts: event.ts, agent: null, error: null }

    if (event.unknown) {
      entries.push({ ...base, type: 'Unrecognised event', description: `The backend sent "${event.name}".`, tone: 'neutral' })
      continue
    }

    const terminal = isTerminal(phase)

    switch (event.name) {
      case 'session_started': {
        const { goal: g, n_initial, budget_usd } = event.payload
        goal = g || null
        startedAt ??= event.ts
        budgetUsd = budget_usd
        initialHypotheses = n_initial
        entries.push({
          ...base,
          type: 'Session started',
          description:
            n_initial !== null
              ? `Research session started. ${n_initial} initial ${n_initial === 1 ? 'hypothesis' : 'hypotheses'} requested.`
              : 'Research session started.',
          tone: 'neutral',
        })
        break
      }

      case 'task_started': {
        const { task_id, agent, action } = event.payload
        // A retried task starts again under the same id
        tasks.set(task_id, { agent, action, state: 'running' })
        tallies[agent].lastAction = action
        anyTaskStarted = true
        if (phase === 'preparing') phase = 'running'
        entries.push({ ...base, agent, type: 'Task started', description: actionLabel(action) ?? 'Task started', tone: 'running' })
        break
      }

      case 'task_completed': {
        const { task_id, kind, follow_hypothesis_ids } = event.payload
        const task = tasks.get(task_id)
        if (task && task.state !== 'completed') {
          task.state = 'completed'
          const tally = tallies[task.agent]
          tally.completed++
          tally.lastOutcome = 'completed'
          tally.lastError = null
        } else if (!task) {
          unattributedResults++
        }
        entries.push({
          ...base,
          agent: task?.agent ?? null,
          type: 'Task completed',
          description: resultLabel(kind, follow_hypothesis_ids),
          tone: 'success',
        })
        break
      }

      case 'task_failed': {
        const { task_id, err } = event.payload
        const task = tasks.get(task_id)
        if (task && task.state === 'running') {
          task.state = 'failed'
          const tally = tallies[task.agent]
          tally.failed++
          tally.lastOutcome = 'failed'
          tally.lastError = err || null
        } else if (!task) {
          unattributedResults++
        }
        entries.push({
          ...base,
          agent: task?.agent ?? null,
          type: 'Task failed',
          description: task ? `${actionLabel(task.action)} failed.` : 'A task failed.',
          error: err || 'No error message was sent.',
          tone: 'error',
        })
        break
      }

      case 'session_paused':
        if (!terminal) phase = 'paused'
        entries.push({ ...base, type: 'Session paused', description: 'No new tasks will start until the session resumes.', tone: 'neutral' })
        break

      case 'session_resumed':
        if (!terminal) phase = anyTaskStarted ? 'running' : 'preparing'
        entries.push({ ...base, type: 'Session resumed', description: 'The session is scheduling tasks again.', tone: 'neutral' })
        break

      case 'session_aborted':
        if (!terminal) phase = 'aborted'
        entries.push({ ...base, type: 'Stop requested', description: 'Tasks already running will finish; no new ones will start.', tone: 'neutral' })
        break

      case 'session_done': {
        const reason = event.payload.stop_reason
        stopReason = reason
        endedAt = event.ts
        // An external stop only comes from an abort, which may be missing from a replay
        if (reason === 'external') phase = 'aborted'
        else if (phase !== 'aborted') phase = 'completed'
        const reasonText = reason ? (STOP_REASON_LABELS[reason] ?? reason) : null
        entries.push({
          ...base,
          type: 'Session finished',
          description: reasonText ? `Research session finished. ${reasonText}.` : 'Research session finished.',
          tone: phase === 'aborted' ? 'neutral' : 'success',
        })
        break
      }

      case 'human_feedback':
        entries.push({ ...base, type: 'Feedback received', description: event.payload.text || 'Feedback was added to the session.', tone: 'neutral' })
        break
    }
  }

  if (options.snapshotStatus === 'failed') phase = 'failed'
  else if (options.snapshotStatus === 'aborted') phase = 'aborted'
  else if (options.snapshotStatus === 'paused' && !isTerminal(phase)) phase = 'paused'

  const ended = isTerminal(phase)
  const running = new Map<AgentName, { count: number; action: string }>()
  for (const task of tasks.values()) {
    if (task.state !== 'running') continue
    const current = running.get(task.agent)
    running.set(task.agent, { count: (current?.count ?? 0) + 1, action: task.action })
  }

  const agents = AGENT_NAMES.map((name): AgentProgress => {
    const tally = tallies[name]
    // Once the session has ended nothing is still running, whatever went unreported
    const inFlight = ended ? undefined : running.get(name)
    const activity: AgentActivity = inFlight ? 'running' : (tally.lastOutcome ?? 'idle')
    return {
      name,
      activity,
      runningCount: inFlight?.count ?? 0,
      completedCount: tally.completed,
      failedCount: tally.failed,
      action: (inFlight?.action ?? tally.lastAction) as TaskAction | null,
      lastError: activity === 'failed' ? tally.lastError : null,
    }
  })

  return {
    phase,
    goal,
    startedAt,
    endedAt,
    budgetUsd,
    initialHypotheses,
    stopReason,
    agents,
    completedTasks: agents.reduce((sum, a) => sum + a.completedCount, 0),
    failedTasks: agents.reduce((sum, a) => sum + a.failedCount, 0),
    unattributedResults,
    entries,
  }
}
