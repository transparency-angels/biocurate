import { KNOWN_EVENT_NAMES, type SseMessage } from '@/types/researchEvents'

export interface EventSourceHandlers {
  onMessage: (message: SseMessage) => void
  onError?: () => void
}

/**
 * Delivers a session's events as raw SSE messages. The dashboard only ever sees this
 * interface, so the demo simulation and the real backend stream are interchangeable.
 */
export interface ResearchEventSource {
  /**
   * Starts delivery. Like the backend endpoint, a source replays what has already happened
   * before sending new events. Returns a function that stops delivery and releases resources.
   */
  connect: (handlers: EventSourceHandlers) => () => void
}

/**
 * Pause, resume and stop for a session. A live implementation will POST to
 * /api/sessions/{id}/pause, /resume and /abort; each change then arrives as an event
 * (session_paused, session_resumed, session_aborted), never as a direct state change.
 */
export interface ResearchSessionControls {
  pause: () => void
  resume: () => void
  abort: () => void
}

/**
 * The live stream from `GET /api/sessions/{sessionId}/events`. Not used yet: nothing in the
 * app constructs it until the API integration phase.
 *
 * The backend sends named SSE events, which a browser EventSource only delivers to
 * listeners registered for that exact name. Events with names outside KNOWN_EVENT_NAMES
 * will not arrive here; add a name to that list to receive it.
 */
export function createSseEventSource(sessionId: string, baseUrl = ''): ResearchEventSource {
  return {
    connect({ onMessage, onError }) {
      const source = new EventSource(`${baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/events`)
      const forward = (event: MessageEvent<string>) => onMessage({ event: event.type, data: event.data })

      for (const name of KNOWN_EVENT_NAMES) source.addEventListener(name, forward)
      source.addEventListener('hypothesis_generated', forward)
      source.addEventListener('hypothesis_reviewed', forward)
      source.addEventListener('match_completed', forward)
      source.addEventListener('match_complete', forward)
      source.addEventListener('timeline_message', forward)
      source.addEventListener('message', forward)
      // EventSource reconnects by itself; the backend then replays its last 25 events,
      // which the adapter de-duplicates
      source.onerror = () => onError?.()

      return () => source.close()
    },
  }
}
