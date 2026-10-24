import type {
  AgentName,
  EventPayloads,
  KnownEventName,
  LiveEventData,
  ReplayEventData,
  TaskAction,
  TaskResultKind,
} from '@/types/researchEvents'
import type { EventSourceHandlers, ResearchEventSource, ResearchSessionControls } from './researchEventSource'

/**
 * A scripted stand-in for the Co-Scientist event stream, for the demo only. No AI runs and
 * nothing is sent to the backend.
 *
 * The script follows the Supervisor's real follow-up rules (agents/supervisor.py): each
 * created hypothesis is reviewed, each review enters the tournament, entries trigger
 * tournament comparisons, and evolution, proximity and meta-review work is scheduled
 * once there is enough to work on. Timings are compressed from minutes to seconds.
 *
 * Messages use the backend's two wire formats: history is replayed as `{payload, ts}` on
 * every connect, and new events are sent as `{name, session_id, payload, ts_ms}`.
 * The log is kept in session storage, so a reload replays it and the run carries on.
 * Unlike the backend, which replays only its last 25 stored events and never stores pause,
 * resume or abort, the simulation replays everything.
 */

type Step = {
  [N in KnownEventName]: { delay: number; event: N; payload: EventPayloads[N] }
}[KnownEventName]

interface LoggedEvent {
  event: KnownEventName
  payload: EventPayloads[KnownEventName]
  ts: number
}

interface SavedSimulation {
  version: 1
  question: string
  cursor: number
  paused: boolean
  aborted: boolean
  log: LoggedEvent[]
}

const STORAGE_KEY = 'biocurate:demo-simulation'
/** The backend's default `run.budget_usd` (config.py); a spending limit, not a cost */
const DEFAULT_BUDGET_USD = 25
const INITIAL_HYPOTHESES = 3

// Shaped like the backend's ids (tsk_ + 26 characters, hyp_ + 16) but marked as demo ids
const taskId = (n: number) => `tsk_01DEMO${String(n).padStart(20, '0')}`
const hypothesisId = (n: number) => `hyp_demo${String(n).padStart(12, '0')}`

function buildScript(question: string): Step[] {
  const steps: Step[] = []
  const start = (delay: number, n: number, agent: AgentName, action: TaskAction, target: number | null = null) =>
    steps.push({
      delay,
      event: 'task_started',
      payload: { task_id: taskId(n), agent, action, target: target === null ? null : hypothesisId(target) },
    })
  const complete = (delay: number, n: number, kind: TaskResultKind, hypotheses: number[] = []) =>
    steps.push({
      delay,
      event: 'task_completed',
      payload: { task_id: taskId(n), kind, follow_hypothesis_ids: hypotheses.map(hypothesisId) },
    })

  steps.push({
    delay: 600,
    event: 'session_started',
    payload: { goal: question.slice(0, 200), n_initial: INITIAL_HYPOTHESES, budget_usd: DEFAULT_BUDGET_USD },
  })

  // The goal is parsed into a research plan, then one generation task per initial hypothesis
  start(2400, 1, 'generation', 'CreateInitialHypotheses')
  start(150, 2, 'generation', 'CreateInitialHypotheses')
  start(150, 3, 'generation', 'CreateInitialHypotheses')

  // Every new hypothesis is queued for a full review
  complete(3200, 1, 'hypothesis_created', [1])
  start(250, 4, 'reflection', 'ReviewHypothesis', 1)
  complete(1100, 2, 'hypothesis_created', [2])
  start(250, 5, 'reflection', 'ReviewHypothesis', 2)
  complete(1300, 3, 'hypothesis_created', [3])
  start(250, 6, 'reflection', 'ReviewHypothesis', 3)

  // A reviewed hypothesis enters the tournament, which queues a comparison focused on it
  complete(2200, 4, 'review_completed', [1])
  start(250, 7, 'ranking', 'AddToTournament', 1)
  steps.push({
    delay: 1200,
    event: 'task_failed',
    payload: { task_id: taskId(5), err: 'Demo failure: the model provider did not respond within the time limit.' },
  })
  complete(800, 7, 'added_to_tournament', [1])
  start(250, 8, 'ranking', 'RunTournamentBatch')
  // A failed task goes back on the queue under the same id while it has attempts left
  start(700, 5, 'reflection', 'ReviewHypothesis', 2)
  complete(1000, 6, 'review_completed', [3])
  start(250, 9, 'ranking', 'AddToTournament', 3)
  // With one hypothesis in the tournament there is nothing to compare yet
  complete(900, 8, 'noop')
  complete(700, 9, 'added_to_tournament', [3])
  start(250, 10, 'ranking', 'RunTournamentBatch')
  complete(1600, 5, 'review_completed', [2])
  start(250, 11, 'ranking', 'AddToTournament', 2)
  complete(1400, 10, 'tournament_match_complete', [1, 3])
  complete(500, 11, 'added_to_tournament', [2])
  start(250, 12, 'ranking', 'RunTournamentBatch')
  complete(1800, 12, 'tournament_match_complete', [2, 1])

  // Periodic work once the tournament has results: similarity grouping and evolution
  start(400, 13, 'proximity', 'UpdateProximityGraph')
  start(200, 14, 'evolution', 'EvolveTopHypotheses')
  complete(1500, 13, 'proximity_updated')
  complete(2600, 14, 'hypothesis_created', [4])
  start(250, 15, 'reflection', 'ReviewHypothesis', 4)
  start(300, 16, 'metareview', 'GenerateSystemFeedback')
  complete(2000, 15, 'review_completed', [4])
  start(250, 17, 'ranking', 'AddToTournament', 4)
  complete(900, 16, 'system_feedback_generated')
  complete(500, 17, 'added_to_tournament', [4])
  start(250, 18, 'ranking', 'RunTournamentBatch')
  complete(1700, 18, 'tournament_match_complete', [4, 1])

  // The final overview is written without task events; session_done follows it
  steps.push({ delay: 2600, event: 'session_done', payload: { stop_reason: 'elo_stable' } })
  return steps
}

function readSaved(question: string): SavedSimulation | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as SavedSimulation
    if (saved?.version !== 1 || saved.question !== question || !Array.isArray(saved.log)) return null
    return saved
  } catch {
    return null
  }
}

/** Forgets the saved demo run, so the next one starts from the beginning. */
export function clearDemoSimulation() {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing stored, nothing to clear
  }
}

export class DemoResearchSimulation implements ResearchEventSource, ResearchSessionControls {
  private readonly sessionId: string
  private readonly question: string
  private readonly script: Step[]
  private cursor = 0
  private paused = false
  private aborted = false
  private log: LoggedEvent[] = []

  private handlers: EventSourceHandlers | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private timerDelay = 0
  private timerStartedAt = 0
  /** Time left on the step that was waiting when the run was paused or disconnected */
  private remaining: number | null = null

  constructor(sessionId: string, question: string) {
    this.sessionId = sessionId
    this.question = question
    this.script = buildScript(question)

    const saved = readSaved(question)
    if (saved) {
      this.cursor = Math.min(saved.cursor, this.script.length)
      this.paused = saved.paused
      this.aborted = saved.aborted
      this.log = saved.log
    }
  }

  // Arrow functions, so the methods keep `this` when passed as callbacks (e.g. onClick)
  connect = (handlers: EventSourceHandlers) => {
    this.handlers = handlers
    const history = [...this.log]
    // Delivered asynchronously, as a network stream would be
    queueMicrotask(() => {
      if (this.handlers !== handlers) return
      for (const { event, payload, ts } of history) {
        handlers.onMessage({ event, data: JSON.stringify({ payload: { ...payload }, ts } satisfies ReplayEventData) })
      }
    })
    this.scheduleNext()

    return () => {
      if (this.handlers !== handlers) return
      this.handlers = null
      this.stopTimer()
    }
  }

  pause = () => {
    if (this.paused || this.aborted || this.finished) return
    this.stopTimer()
    this.paused = true
    this.emit('session_paused', {})
  }

  resume = () => {
    if (!this.paused) return
    this.paused = false
    this.emit('session_resumed', {})
    this.scheduleNext()
  }

  /** Like the backend: tasks already running finish, then the session ends as an external stop. */
  abort = () => {
    if (this.aborted || this.finished) return
    this.stopTimer()
    this.remaining = null
    this.aborted = true
    this.paused = false
    this.emit('session_aborted', {})
    this.scheduleNext()
  }

  private get finished() {
    return this.log.some((entry) => entry.event === 'session_done')
  }

  private nextStep(): Step | null {
    if (!this.aborted) return this.script[this.cursor] ?? null

    // Draining after a stop: finish each task still running, then end the session
    const running = new Set<string>()
    for (const { event, payload } of this.log) {
      if (event === 'task_started') running.add((payload as EventPayloads['task_started']).task_id)
      if (event === 'task_completed' || event === 'task_failed') {
        running.delete((payload as EventPayloads['task_completed']).task_id)
      }
    }
    for (const id of running) {
      const completion = this.script.find((step) => step.event === 'task_completed' && step.payload.task_id === id)
      if (completion) return { ...completion, delay: 700 }
    }
    return { delay: 900, event: 'session_done', payload: { stop_reason: 'external' } }
  }

  private scheduleNext() {
    if (this.timer || !this.handlers || this.paused || this.finished) return
    const step = this.nextStep()
    if (!step) return

    this.timerDelay = this.remaining ?? step.delay
    this.timerStartedAt = Date.now()
    this.timer = setTimeout(() => {
      this.timer = null
      this.remaining = null
      if (!this.aborted) this.cursor++
      this.emit(step.event, step.payload)
      this.scheduleNext()
    }, this.timerDelay)
  }

  private stopTimer() {
    if (!this.timer) return
    clearTimeout(this.timer)
    this.timer = null
    this.remaining = Math.max(0, this.timerDelay - (Date.now() - this.timerStartedAt))
  }

  private emit<N extends KnownEventName>(event: N, payload: EventPayloads[N]) {
    const ts = Date.now()
    this.log.push({ event, payload, ts })
    this.save()
    const data: LiveEventData = { name: event, session_id: this.sessionId, payload: { ...payload }, ts_ms: ts }
    this.handlers?.onMessage({ event, data: JSON.stringify(data) })
  }

  private save() {
    const state: SavedSimulation = {
      version: 1,
      question: this.question,
      cursor: this.cursor,
      paused: this.paused,
      aborted: this.aborted,
      log: this.log,
    }
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      // Storage blocked: the demo still runs, it just restarts on reload
    }
  }
}
