import { Pause, Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { isTerminal, type SessionPhase } from '@/services/eventAdapter'
import type { ResearchSessionControls } from '@/services/researchEventSource'

interface ResearchControlsProps {
  phase: SessionPhase
  started: boolean
  controls: ResearchSessionControls
}

const buttonClass = 'h-11 gap-2 rounded-full px-4 sm:h-9'

export function ResearchControls({ phase, started, controls }: ResearchControlsProps) {
  const active = started && !isTerminal(phase)
  return (
    <div role="group" aria-label="Research session controls" className="flex flex-wrap items-center gap-x-2 gap-y-3 border-t border-border px-5 py-3 sm:px-6">
      <p className="w-full text-[0.8125rem] leading-5 text-muted-foreground lg:mr-auto lg:w-auto">Controls apply to this research session.</p>
      {phase === 'paused' ? (
        <Button variant="outline" onClick={controls.resume} className={buttonClass}><Play aria-hidden="true" />Resume</Button>
      ) : (
        <Button variant="outline" onClick={controls.pause} disabled={!active} className={buttonClass}><Pause aria-hidden="true" />Pause</Button>
      )}
      <Button variant="destructive" onClick={controls.abort} disabled={!active} className={buttonClass}><Square aria-hidden="true" />Stop</Button>
    </div>
  )
}
