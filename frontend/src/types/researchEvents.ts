/**
 * Mirrors the Co-Scientist backend's session event stream, as read from the Python source:
 *
 * - co_scientist/agents/supervisor.py (Supervisor._emit): session_started, task_started,
 *   task_completed, task_failed, session_done
 * - co_scientist/web/app.py (pause / resume / abort / feedback endpoints): session_paused,
 *   session_resumed, session_aborted, human_feedback
 * - co_scientist/models/task.py and session.py: agents, actions, result kinds, statuses
 * - co_scientist/orchestrator/termination.py (StopReason): stop reasons
 *
 * Field names keep the backend's snake_case so payloads can be read without renaming.
 */

/** TaskAgent in models/task.py */
export const AGENT_NAMES = [
  'generation',
  'reflection',
  'ranking',
  'evolution',
  'proximity',
  'metareview',
] as const
export type AgentName = (typeof AGENT_NAMES)[number]

/** TaskAction in models/task.py */
export type TaskAction =
  | 'CreateInitialHypotheses'
  | 'GenerateFromFeedback'
  | 'DirectGeneration'
  | 'ReviewHypothesis'
  | 'AddToTournament'
  | 'RunTournamentBatch'
  | 'EvolveTopHypotheses'
  | 'UpdateProximityGraph'
  | 'GenerateSystemFeedback'
  | 'GenerateFinalResearchOverview'

/** TaskResultKind in models/task.py */
export type TaskResultKind =
  | 'hypothesis_created'
  | 'review_completed'
  | 'added_to_tournament'
  | 'tournament_match_complete'
  | 'proximity_updated'
  | 'evolution_completed'
  | 'system_feedback_generated'
  | 'final_overview_generated'
  | 'noop'

/** SessionStatus in models/session.py */
export type BackendSessionStatus = 'running' | 'paused' | 'done' | 'failed' | 'aborted'

/** StopReason in orchestrator/termination.py; session_done sends null when there was none */
export type StopReason = 'budget' | 'wall_clock' | 'elo_stable' | 'external' | 'idle'

// ----------------------------- payloads ----------------------------- //

export interface SessionStartedPayload {
  /** The research goal, cut to 200 characters by the backend */
  goal: string
  /** Always sent by the current backend; null only if a payload arrives without it */
  n_initial: number | null
  /** The session's spending limit in US dollars, not money spent. Null as above. */
  budget_usd: number | null
}

export interface TaskStartedPayload {
  task_id: string
  agent: AgentName
  action: TaskAction
  /** Hypothesis the task works on; the backend names this `target` (Task.target_id) */
  target: string | null
}

/** Carries no agent: it must be matched to its task_started by task_id */
export interface TaskCompletedPayload {
  task_id: string
  kind: TaskResultKind
  /** At most the first five ids of TaskResult.hypothesis_ids */
  follow_hypothesis_ids: string[]
}

/** Carries no agent either. A failed task may be retried under the same task_id. */
export interface TaskFailedPayload {
  task_id: string
  /** The exception text, cut to 300 characters */
  err: string
}

export interface SessionDonePayload {
  stop_reason: StopReason | null
}

export interface HumanFeedbackPayload {
  kind: string
  target_id: string | null
  text: string
}

/** session_paused, session_resumed and session_aborted are published with an empty payload */
export type EmptyPayload = Record<string, never>

export interface EventPayloads {
  session_started: SessionStartedPayload
  task_started: TaskStartedPayload
  task_completed: TaskCompletedPayload
  task_failed: TaskFailedPayload
  session_paused: EmptyPayload
  session_resumed: EmptyPayload
  session_aborted: EmptyPayload
  session_done: SessionDonePayload
  human_feedback: HumanFeedbackPayload
}

export type KnownEventName = keyof EventPayloads

export const KNOWN_EVENT_NAMES = [
  'session_started',
  'task_started',
  'task_completed',
  'task_failed',
  'session_paused',
  'session_resumed',
  'session_aborted',
  'session_done',
  'human_feedback',
] as const satisfies readonly KnownEventName[]

// ----------------------------- wire format ----------------------------- //

/**
 * One server-sent event as `GET /api/sessions/{id}/events` sends it: the SSE event name
 * plus its `data` string. A browser EventSource hands over exactly these two fields.
 */
export interface SseMessage {
  event: string
  data: string
}

/** `data` of the up-to-25 events replayed from the database when a client connects */
export interface ReplayEventData {
  payload: Record<string, unknown> | null
  /** Epoch milliseconds */
  ts: number
}

/** `data` of events published live on the in-process bus (orchestrator/events.py Event) */
export interface LiveEventData {
  name: string
  session_id: string
  payload: Record<string, unknown>
  /** Epoch milliseconds */
  ts_ms: number
}

// ----------------------------- normalised ----------------------------- //

interface EventBase {
  /** Epoch milliseconds, from `ts` (replay) or `ts_ms` (live) */
  ts: number
  /** Which wire format the event arrived in */
  origin: 'replay' | 'live'
  /** Stable identity used to drop the same event when it arrives twice */
  key: string
}

export type KnownResearchEvent = {
  [N in KnownEventName]: EventBase & { name: N; unknown?: false; payload: EventPayloads[N] }
}[KnownEventName]

/** An event the frontend does not recognise. Kept for the activity log, ignored by state. */
export interface UnknownResearchEvent extends EventBase {
  name: string
  unknown: true
  payload: Record<string, unknown>
}

export type ResearchEvent = KnownResearchEvent | UnknownResearchEvent
