import { lazy, Suspense, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ArrowRight, Clock3 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { BioCurateWordmark } from '@/components/brand/BioCurateWordmark'
import { WhatWeOffer } from '@/components/home/WhatWeOffer'
import { ResearchComposer } from '@/features/research/ResearchComposer'
import type { SubmitResearch } from '@/features/research/types'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { readCurrentSession, subscribeCurrentSession, type CurrentSession } from '@/features/research/currentSession'
import { getSession } from '@/services/api'

// Loaded separately so the particle engine never delays the first paint of the prompt
const MolecularBackground = lazy(() => import('@/components/background/MolecularBackground'))

interface HomePageProps {
  onSubmitResearch: SubmitResearch
}

export function HomePage({ onSubmitResearch }: HomePageProps) {
  const [currentSession, setCurrentSession] = useState<CurrentSession | null>(null)
  useEffect(() => {
    let active = true
    const refresh = () => {
      const stored = readCurrentSession()
      setCurrentSession(stored)
      if (stored) void getSession(stored.id).then((session) => {
        if (active && readCurrentSession()?.id === stored.id) setCurrentSession({ ...stored, question: session.research_goal })
      }).catch(() => undefined)
    }
    refresh()
    const unsubscribe = subscribeCurrentSession(refresh)
    return () => { active = false; unsubscribe() }
  }, [])
  useDocumentTitle()

  return (
    <div className="flex flex-1 flex-col bg-background">
      {/* The hero keeps the molecular field to itself; it fills most of the first screen
          and leaves the top of the next section in view */}
      <div className="relative isolate flex min-h-[calc(100dvh-24rem)] flex-col items-center justify-center overflow-hidden px-4 pt-10 pb-12">
        <Suspense fallback={null}>
          <MolecularBackground />
        </Suspense>
        <div className="flex w-full max-w-[44rem] flex-col items-center motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-500">
          <h1 className="text-[2.125rem] leading-none text-foreground sm:text-[2.5rem]">
            <BioCurateWordmark />
            <span className="sr-only"> AI</span>
          </h1>
          <p className="mt-3.5 text-center font-serif text-[1.1875rem] leading-7 text-balance text-foreground sm:text-[1.3125rem] sm:leading-8">
            Where <span className="font-semibold">Curiosity</span> Sparks Discoveries.
          </p>

          <div className="mt-8 w-full">
            {currentSession && (
              <section className="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-card/90 px-4 py-3.5 text-left shadow-sm backdrop-blur-sm sm:px-5">
                <div className="flex min-w-0 items-start gap-3">
                  <Clock3 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-brand" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-muted-foreground">Your recent research</p>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-foreground">{currentSession.question ?? 'Open your latest research session.'}</p>
                  </div>
                </div>
                <Button asChild variant="outline" className="h-9 shrink-0 gap-2 rounded-full px-3.5">
                  <Link to={`/research/${currentSession.id}/progress`}>Continue<ArrowRight aria-hidden="true" className="size-4" /></Link>
                </Button>
              </section>
            )}
            <ResearchComposer onSubmit={onSubmitResearch} />
          </div>
        </div>
      </div>

      <WhatWeOffer className="px-4 pt-2 pb-20 sm:px-6 sm:pb-24" />

      <footer className="px-4 pb-6 text-center text-[0.8125rem] leading-5 text-faint">
        BioCurate AI can make mistakes. Check important findings against primary sources.
      </footer>
    </div>
  )
}
