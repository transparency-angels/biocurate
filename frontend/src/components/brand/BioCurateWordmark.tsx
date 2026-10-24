import { FlaskConical } from 'lucide-react'
import { cn } from '@/lib/utils'

export function BioCurateWordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <FlaskConical aria-hidden="true" className="size-[0.9em] text-brand" strokeWidth={1.75} />
      <span className="font-semibold tracking-[-0.02em]">BioCurate</span>
    </span>
  )
}
