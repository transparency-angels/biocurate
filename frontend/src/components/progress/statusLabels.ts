import type { ActivityTone, AgentActivity, SessionPhase } from '@/services/eventAdapter'

export const TONE_CLASSES: Record<ActivityTone, { pill: string; dot: string }> = {
  neutral: { pill: 'bg-secondary text-muted-foreground', dot: 'bg-muted-foreground' },
  running: { pill: 'bg-brand/15 text-brand', dot: 'bg-brand' },
  success: { pill: 'bg-success/15 text-success', dot: 'bg-success' },
  error: { pill: 'bg-destructive/15 text-destructive', dot: 'bg-destructive' },
}

export const toneDotClass = (tone: ActivityTone) => TONE_CLASSES[tone].dot

export const PHASE_STATUS: Record<SessionPhase, { label: string; tone: ActivityTone }> = {
  preparing: { label: 'Preparing', tone: 'running' },
  running: { label: 'Running', tone: 'running' },
  paused: { label: 'Paused', tone: 'neutral' },
  completed: { label: 'Completed', tone: 'success' },
  failed: { label: 'Failed', tone: 'error' },
  aborted: { label: 'Aborted', tone: 'neutral' },
}

export const AGENT_STATUS: Record<AgentActivity, { label: string; tone: ActivityTone }> = {
  idle: { label: 'Idle', tone: 'neutral' },
  running: { label: 'Running', tone: 'running' },
  completed: { label: 'Task completed', tone: 'success' },
  failed: { label: 'Task failed', tone: 'error' },
}

/** "0:42", "12:05" or "1:03:20" */
export function formatDuration(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
export const formatClockTime = (ts: number) => timeFormat.format(ts)
