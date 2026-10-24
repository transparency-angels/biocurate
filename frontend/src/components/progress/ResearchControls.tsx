import { Pause, Play, RotateCcw, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { isTerminal, type SessionPhase } from '@/services/eventAdapter'
import type { ResearchSessionControls } from '@/services/researchEventSource'

interface ResearchControlsProps {
  phase: SessionPhase
  /** False until the session has started, so there is nothing to pause or stop yet */
  started: boolean
  controls: ResearchSessionControls
  onRestart: () => void
}

const buttonClass = 'h-11 gap-2 rounded-full px-4 sm:h-9'

/** Pause, resume, stop and restart for the demo simulation. None of these reach the backend. */
export function ResearchControls({ phase, started, controls, onRestart }: ResearchControlsProps) {
  const active = started && !isTerminal(phase)

  return (
    <div
      role="group"
      aria-label="Demo controls"
      className="flex flex-wrap items-center gap-x-2 gap-y-3 border-t border-border px-5 py-3 sm:px-6"
    >
      <p className="w-full text-[0.8125rem] leading-5 text-muted-foreground lg:mr-auto lg:w-auto">
        Demo controls. They act on the simulation only.
      </p>

      {phase === 'paused' ? (
        <Button variant="outline" onClick={controls.resume} className={buttonClass}>
          <Play aria-hidden="true" />
          Resume
        </Button>
      ) : (
        <Button variant="outline" onClick={controls.pause} disabled={!active} className={buttonClass}>
          <Pause aria-hidden="true" />
          Pause
        </Button>
      )}
      <Button variant="destructive" onClick={controls.abort} disabled={!active} className={buttonClass}>
        <Square aria-hidden="true" />
        Stop
      </Button>
      <Button variant="ghost" onClick={onRestart} className={buttonClass}>
        <RotateCcw aria-hidden="true" />
        Restart demo
      </Button>
    </div>
  )
}
