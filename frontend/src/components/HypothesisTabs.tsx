import { Tabs } from 'radix-ui'
import { ChartColumn, FileText, Link2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Hypothesis } from '@/types/research'
import { EvaluationTab } from './tabs/EvaluationTab'
import { DataTab } from './tabs/DataTab'
import { SourcesTab } from './tabs/SourcesTab'

export type HypothesisTab = 'evaluation' | 'data' | 'sources'

const TABS = [
  { value: 'evaluation', label: 'Hypothesis', icon: FileText },
  { value: 'data', label: 'Data', icon: ChartColumn },
  { value: 'sources', label: 'Sources', icon: Link2 },
] as const satisfies { value: HypothesisTab; label: string; icon: unknown }[]

// Data and Sources scroll inside the panel on desktop only. Below `lg` the panel
// stacks under the list and the page scrolls, so touch never meets a nested scroller.
const scrollPanel = 'lg:max-h-[32rem] lg:overflow-y-auto lg:overscroll-contain'
const sourcesScrollPanel = 'lg:max-h-[48rem] lg:overflow-y-auto lg:overscroll-contain'

interface HypothesisTabsProps {
  id: string
  sessionId: string
  hypothesis: Hypothesis
  total: number
  activeTab: HypothesisTab
  onTabChange: (tab: HypothesisTab) => void
}

export function HypothesisTabs({ id, sessionId, hypothesis, total, activeTab, onTabChange }: HypothesisTabsProps) {
  const contentClass = 'outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset'

  return (
    <section
      id={id}
      aria-label={`Details for hypothesis ${hypothesis.rank}`}
      className="min-w-0 overflow-hidden rounded-xl border border-border bg-card"
    >
      <Tabs.Root value={activeTab} onValueChange={(value) => onTabChange(value as HypothesisTab)}>
        <Tabs.List aria-label="Hypothesis details" className="flex border-b border-border px-2 sm:px-4">
          {TABS.map(({ value, label, icon: Icon }) => (
            <Tabs.Trigger
              key={value}
              value={value}
              className={cn(
                'relative flex h-12 flex-1 items-center justify-center gap-2 rounded-t-md text-sm font-medium text-muted-foreground transition-colors outline-none',
                'hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset',
                'after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:content-[""]',
                'data-[state=active]:text-foreground data-[state=active]:after:bg-brand',
              )}
            >
              <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {/* Keyed by hypothesis so each one opens at the top of its panel */}
        <Tabs.Content key={`evaluation-${hypothesis.id}`} value="evaluation" className={contentClass}>
          <EvaluationTab hypothesis={hypothesis} total={total} />
        </Tabs.Content>
        <Tabs.Content key={`data-${hypothesis.id}`} value="data" className={cn(contentClass, scrollPanel)}>
          <DataTab hypothesis={hypothesis} sessionId={sessionId} />
        </Tabs.Content>
        <Tabs.Content key={`sources-${hypothesis.id}`} value="sources" className={cn(contentClass, sourcesScrollPanel)}>
          <SourcesTab hypothesis={hypothesis} sessionId={sessionId} />
        </Tabs.Content>
      </Tabs.Root>
    </section>
  )
}
