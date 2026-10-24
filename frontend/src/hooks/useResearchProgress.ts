import { useEffect, useMemo, useState } from 'react'
import { ingestEvent, parseSseMessage, reduceEvents, type ReduceOptions } from '@/services/eventAdapter'
import type { ResearchEventSource } from '@/services/researchEventSource'
import type { ResearchEvent } from '@/types/researchEvents'

/**
 * Subscribes to a session's events and returns the dashboard state derived from them.
 * Works the same for the demo simulation and the live SSE source. Remount the caller
 * (for example with a new `key`) to start over with a different source.
 */
export function useResearchProgress(source: ResearchEventSource, options?: ReduceOptions) {
  const [events, setEvents] = useState<ResearchEvent[]>([])
  const [connectionLost, setConnectionLost] = useState(false)

  useEffect(() => {
    return source.connect({
      onMessage: (message) => {
        const event = parseSseMessage(message)
        if (!event) return
        setConnectionLost(false)
        // ingestEvent returns the same list for a duplicate, so re-sent events change nothing
        setEvents((current) => ingestEvent(current, event))
      },
      onError: () => setConnectionLost(true),
    })
  }, [source])

  const snapshotStatus = options?.snapshotStatus
  const progress = useMemo(() => reduceEvents(events, { snapshotStatus }), [events, snapshotStatus])

  return { progress, connectionLost }
}

/** The current time, refreshed every second while `active`; for elapsed-time displays. */
export function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])

  return now
}
