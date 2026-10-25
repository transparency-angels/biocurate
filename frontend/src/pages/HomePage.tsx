import { lazy, Suspense } from 'react'
import { BioCurateWordmark } from '@/components/brand/BioCurateWordmark'
import { WhatWeOffer } from '@/components/home/WhatWeOffer'
import { ResearchComposer } from '@/features/research/ResearchComposer'
import type { SubmitResearch } from '@/features/research/types'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Loaded separately so the particle engine never delays the first paint of the prompt
const MolecularBackground = lazy(() => import('@/components/background/MolecularBackground'))

interface HomePageProps {
  onSubmitResearch: SubmitResearch
}

export function HomePage({ onSubmitResearch }: HomePageProps) {
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
