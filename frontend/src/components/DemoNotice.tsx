import type { ReactNode } from 'react'
import { Info } from 'lucide-react'

/** One-line reminder that the content around it is demonstration material. */
export function DemoNotice({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-[0.8125rem] leading-5 text-muted-foreground">
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-brand" strokeWidth={1.75} />
      <span>{children}</span>
    </p>
  )
}
