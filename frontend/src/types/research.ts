/**
 * Shapes for research results. Kept flat and serialisable so the mock module can
 * later be swapped for the Co-Scientist FastAPI responses without UI changes.
 */

export type EvidenceType = 'Experimental study' | 'Dataset' | 'Review' | 'Clinical study'

export interface SourceRecord {
  id: string
  title: string
  publication: string
  year: number | null
  evidenceType: EvidenceType
  description: string
  /** Only set for a verified link. Without one the card shows "Source link unavailable". */
  url: string | null
}

export interface DataPoint {
  id: string
  label: string
  group: string
  value: number
}

export interface DataSummary {
  description: string
  metric: string
  unit: string
}

export interface Hypothesis {
  id: string
  rank: number
  state?: 'draft' | 'reviewed' | 'in_tournament' | 'pinned' | 'rejected' | 'quarantined' | 'retired'
  createdAt?: string
  elo?: number | null
  matchesPlayed?: number
  candidateKey?: string | null
  dataEvidence?: Record<string, unknown> | null
  title: string
  summary: string
  abstract: string
  explanation: string
  dataSummary: DataSummary
  dataPoints: DataPoint[]
  sources: SourceRecord[]
}

export interface ResearchSession {
  id: string
  isDemo: boolean
  hypotheses: Hypothesis[]
}
