import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { DemoBadge } from '@/components/DemoBadge'
import { AgentWorkflow } from '@/components/progress/AgentWorkflow'
import { ResearchActivity } from '@/components/progress/ResearchActivity'
import { ResearchControls } from '@/components/progress/ResearchControls'
import { ResearchSessionHeader } from '@/components/progress/ResearchSessionHeader'
import { PHASE_STATUS } from '@/components/progress/statusLabels'
import { Button } from '@/components/ui/button'
import { DEMO_SESSION_ID } from '@/data/mockHypotheses'
import { DEMO_RESULTS_PATH, readDemoQuestion } from '@/features/research/demoQuestion'
import { useResearchProgress } from '@/hooks/useResearchProgress'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { isTerminal } from '@/services/eventAdapter'
import { DemoResearchSimulation, clearDemoSimulation } from '@/services/mockEventSource'
import { NotFoundPage } from './NotFoundPage'

function TitleRow({ action }: { action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Research progress</h1>
          <DemoBadge />
        </div>
        <p className="mt-1 max-w-[42rem] text-sm leading-6 text-muted-foreground">
          A simulated session for design review. No AI research is running and no backend session was created.
        </p>
      </div>
      {action}
    </div>
  )
}

interface DemoRunProps {
  question: string
  onRestart: () => void
}

/** One run of the simulation. Remounted with a new key to restart from the beginning. */
function DemoRun({ question, onRestart }: DemoRunProps) {
  const [simulation] = useState(() => new DemoResearchSimulation(DEMO_SESSION_ID, question))
  const { progress } = useResearchProgress(simulation)
  const finished = isTerminal(progress.phase)

  return (
    <>
      <TitleRow
        action={
          finished ? (
            <Button asChild className="h-11 gap-2 rounded-full px-4 sm:h-9">
              <Link to={DEMO_RESULTS_PATH}>
                View demo results
                <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
          ) : (
            <p className="pt-1.5 text-[0.8125rem] text-muted-foreground sm:pt-2">
              Demo results open here when the session finishes.
            </p>
          )
        }
      />

      {/* Announces status changes only; the activity log itself stays quiet */}
      <p role="status" className="sr-only">
        Session status: {PHASE_STATUS[progress.phase].label}
      </p>

      <div className="mt-6">
        <ResearchSessionHeader question={question} progress={progress}>
          <ResearchControls
            phase={progress.phase}
            started={progress.startedAt !== null}
            controls={simulation}
            onRestart={onRestart}
          />
        </ResearchSessionHeader>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-stretch">
        <AgentWorkflow progress={progress} />
        {/* Sized by the agents column on desktop; capped so the page never becomes one long log */}
        <div className="relative min-h-[24rem] max-lg:h-[28rem]">
          <ResearchActivity entries={progress.entries} className="lg:absolute lg:inset-0 max-lg:h-full" />
        </div>
      </div>
    </>
  )
}

export function ResearchProgress() {
  const { sessionId } = useParams()
  const [question] = useState(readDemoQuestion)
  const [runId, setRunId] = useState(0)
  const isDemo = sessionId === DEMO_SESSION_ID
  useDocumentTitle(isDemo ? 'Research progress' : 'Research session not found')

  if (!isDemo) {
    return (
      <NotFoundPage
        title="Research session not found"
        message="Real research sessions are not available in this prototype yet. Only the demo session exists."
      />
    )
  }

  function restart() {
    clearDemoSimulation()
    setRunId((id) => id + 1)
  }

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      {question ? (
        <DemoRun key={runId} question={question} onRestart={restart} />
      ) : (
        <>
          <TitleRow />
          <section className="mt-6 rounded-xl border border-border bg-card px-5 py-5 sm:px-6">
            <h2 className="text-base font-semibold text-foreground">No research question yet</h2>
            <p className="mt-1 max-w-[36rem] text-sm leading-6 text-muted-foreground">
              Ask a question on the home page to watch a simulated session with the six Co-Scientist agents.
            </p>
            <Button asChild className="mt-4 h-11 rounded-full px-4 sm:h-9">
              <Link to="/">Ask a question</Link>
            </Button>
          </section>
        </>
      )}
    </div>
  )
}
