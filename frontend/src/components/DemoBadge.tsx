import { cn } from '@/lib/utils'

export function DemoBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 flex-none items-center rounded-full bg-brand/15 px-2.5 text-xs font-medium text-brand',
        className,
      )}
    >
      Demo data
    </span>
  )
}
