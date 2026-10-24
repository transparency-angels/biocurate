import { DemoNotice } from '@/components/DemoNotice'
import type { Hypothesis } from '@/types/research'
import { SourceCard } from './SourceCard'

export function SourcesTab({ hypothesis }: { hypothesis: Hypothesis }) {
  const { sources } = hypothesis

  return (
    <div className="px-5 py-6 sm:px-8">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-sm font-semibold text-foreground">Verifiable experiment records</h3>
        <p className="text-xs text-muted-foreground tabular-nums">
          {sources.length} {sources.length === 1 ? 'record' : 'records'}
        </p>
      </div>
      <div className="mt-3">
        <DemoNotice>Demonstration records, not real citations. Links appear only once a source is verified.</DemoNotice>
      </div>

      {sources.length > 0 ? (
        <ul className="mt-5 space-y-3">
          {sources.map((source) => (
            <li key={source.id}>
              <SourceCard source={source} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-5 rounded-xl border border-border px-5 py-6 text-sm text-muted-foreground">
          No source records for this hypothesis.
        </p>
      )}
    </div>
  )
}
