import { Compass, Lightbulb, Microscope, type LucideIcon } from 'lucide-react'
import type { AgentName } from '@/types/researchEvents'

export type OfferingAccent = 'blue' | 'teal' | 'amber'

export interface Offering {
  title: string
  description: string
  icon: LucideIcon
  accent: OfferingAccent
  /** The existing Co-Scientist agents that carry out this part of a session */
  agents: AgentName[]
}

/**
 * What a research session does, grouped by stage. These describe one combined workflow,
 * not separate products: every session uses all six agents.
 */
export const OFFERINGS: Offering[] = [
  {
    title: 'Hypothesis Generation',
    description:
      'Generate novel, research-grounded hypotheses from your question and the source material you attach.',
    icon: Lightbulb,
    accent: 'blue',
    agents: ['generation', 'evolution'],
  },
  {
    title: 'Evidence Evaluation',
    description:
      'Assess the strength, limitations and relevance of the evidence behind each hypothesis, and group those that overlap.',
    icon: Microscope,
    accent: 'teal',
    agents: ['reflection', 'proximity'],
  },
  {
    title: 'Research Prioritisation',
    description:
      'Compare hypotheses against each other and surface the directions worth taking into the lab first.',
    icon: Compass,
    accent: 'amber',
    agents: ['ranking', 'metareview'],
  },
]
