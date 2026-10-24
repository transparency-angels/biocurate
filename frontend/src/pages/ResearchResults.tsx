import { useId, useState } from 'react'
import { Link, useParams } from 'react-router'
import { DemoBadge } from '@/components/DemoBadge'
import { HypothesisList } from '@/components/HypothesisList'
import { HypothesisTabs, type HypothesisTab } from '@/components/HypothesisTabs'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { getResearchSession } from '@/data/mockHypotheses'
import { readDemoQuestion } from '@/features/research/demoQuestion'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { NotFoundPage } from './NotFoundPage'

export function ResearchResults() {
  const { sessionId } = useParams()
  const session = getResearchSession(sessionId)
  const [question] = useState(readDemoQuestion)
  const [selectedId, setSelectedId] = useState(session?.hypotheses[0]?.id)
  const [activeTab, setActiveTab] = useState<HypothesisTab>('evaluation')
  const detailsId = useId()
  const questionHeadingId = useId()
  // Parent effects run after the child's, so this also titles the not-found state
  useDocumentTitle(session ? 'Research results' : 'Research session not found')

  if (!session || session.hypotheses.length === 0) {
    return (
      <NotFoundPage
        title="Research session not found"
        message="Real research sessions are not available in this prototype yet. Only the demo session exists."
      />
    )
  }

  const selected = session.hypotheses.find((h) => h.id === selectedId) ?? session.hypotheses[0]

  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Research results</h1>
            {session.isDemo && <DemoBadge />}
          </div>
          {session.isDemo && (
            <p className="mt-1 text-sm text-muted-foreground">
              Example content for design review. No AI research workflow has run for this session.
            </p>
          )}
        </div>
        <ResearchViewSwitch sessionId={session.id} />
      </div>

      <section
        aria-labelledby={questionHeadingId}
        className="mt-6 rounded-xl border border-border bg-card px-5 py-4 sm:px-6"
      >
        <h2 id={questionHeadingId} className="text-xs text-muted-foreground">
          Your research question
        </h2>
        {question ? (
          <p className="mt-1.5 font-serif text-[1.0625rem] leading-7 break-words whitespace-pre-line text-foreground">
            {question}
          </p>
        ) : (
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            No question has been submitted in this session.{' '}
            <Link
              to="/"
              className="rounded-sm font-medium text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              Ask a question
            </Link>{' '}
            to see it here alongside the demo hypotheses.
          </p>
        )}
      </section>

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:items-start lg:gap-8">
        <HypothesisList
          hypotheses={session.hypotheses}
          selectedId={selected.id}
          detailsId={detailsId}
          onSelect={setSelectedId}
        />
        <HypothesisTabs
          id={detailsId}
          hypothesis={selected}
          total={session.hypotheses.length}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      </div>
    </div>
  )
}
