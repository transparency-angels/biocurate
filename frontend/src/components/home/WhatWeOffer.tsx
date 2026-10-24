import { useId } from 'react'
import { cn } from '@/lib/utils'
import { OfferingCard } from './OfferingCard'
import { OFFERINGS } from './offerings'

export function WhatWeOffer({ className }: { className?: string }) {
  const headingId = useId()

  return (
    <section aria-labelledby={headingId} className={cn('mx-auto w-full max-w-[68rem]', className)}>
      <h2 id={headingId} className="text-[1.375rem] leading-tight font-semibold tracking-[-0.015em] text-foreground sm:text-[1.5rem]">
        What we offer
      </h2>

      {/* Three columns only where each card has room for its title on one or two lines */}
      <ul className="mt-6 grid gap-4 lg:grid-cols-3 lg:gap-5">
        {OFFERINGS.map((offering) => (
          <OfferingCard key={offering.title} offering={offering} />
        ))}
      </ul>
    </section>
  )
}
