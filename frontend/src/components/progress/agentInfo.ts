import { BarChart3, GitMerge, Lightbulb, Network, ScrollText, SearchCheck, Trophy, type LucideIcon } from 'lucide-react'
import type { AgentName } from '@/types/researchEvents'

export interface AgentInfo {
  icon: LucideIcon
  description: string
}

export const AGENT_INFO: Record<AgentName, AgentInfo> = {
  generation: { icon: Lightbulb, description: 'Creates initial scientific hypotheses.' },
  reflection: { icon: SearchCheck, description: 'Evaluates scientific evidence, correctness and feasibility.' },
  ranking: { icon: Trophy, description: 'Compares hypotheses and ranks the most promising ideas.' },
  evolution: { icon: GitMerge, description: 'Combines, improves and refines hypotheses.' },
  proximity: { icon: Network, description: 'Identifies similar or duplicate hypotheses.' },
  metareview: { icon: ScrollText, description: 'Summarises the research process and final findings.' },
  data_analysis: { icon: BarChart3, description: 'Profiles and analyses the dataset you provided.' },
}
