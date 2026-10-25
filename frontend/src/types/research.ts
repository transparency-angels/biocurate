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
  /** True for an observed event, false for a censored observation; null when not recorded */
  event: boolean | null
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
  title: string
  summary: string
  abstract: string
  explanation: string
  dataSummary: DataSummary
  dataPoints: DataPoint[]
  dataAnalysis: DataAnalysis
  sources: SourceRecord[]
}

export interface ResearchSession {
  id: string
  isDemo: boolean
  hypotheses: Hypothesis[]
}

/**
 * What the session's own data says about a hypothesis. Computed from the uploaded
 * data, never from the model-written hypothesis text.
 *
 * - `supported`: the comparison survives false discovery rate correction
 * - `nominal`: p is below alpha, but not after correcting for every comparison tested
 * - `not_significant`: the data was tested and showed no clear effect
 * - `not_tested`: no analysed comparison matches this hypothesis
 */
export type DataVerdict = 'supported' | 'nominal' | 'not_significant' | 'not_tested'

export interface SurvivalGroup {
  group: 'altered' | 'unaltered'
  label: string
  n: number
  events: number | null
  censored: number | null
  /** Median survival; null when the curve never drops to 50% */
  median: number | null
}

export interface SurvivalStep {
  t: number
  s: number
  lower: number
  upper: number
}

export interface SurvivalCurve {
  group: SurvivalGroup['group']
  label: string
  /** Kaplan-Meier steps from t = 0, with 95% Greenwood log-log bands */
  steps: SurvivalStep[]
  /** Times of censored observations, one entry per sample */
  censored: number[]
}

export interface AtRiskRow {
  t: number
  altered: number
  unaltered: number
}

export interface DataCaveat {
  level: 'warning' | 'info'
  text: string
  /** A suggested next check that would address the caveat */
  action: string
}

export interface RelatedFinding {
  title: string
  detail: string
  test: string
  effect: string
  pValue: number | null
  qValue: number | null
}

export interface DataAnalysis {
  kind: 'survival' | 'exploratory' | 'none'
  status: DataVerdict
  /** One plain sentence stating the finding */
  headline: string
  endpoint: { label: string; unit: string } | null
  groups: SurvivalGroup[]
  effect: {
    medianDifference: number | null
    hazardRatio: number | null
    hazardRatioLower: number | null
    hazardRatioUpper: number | null
    direction: 'worse' | 'better' | 'unclear'
  } | null
  significance: {
    pValue: number | null
    qValue: number | null
    alpha: number
    testsRun: number | null
  } | null
  curves: SurvivalCurve[]
  atRisk: AtRiskRow[]
  caveats: DataCaveat[]
  methods: { label: string; value: string }[]
  /** For non-survival data: findings about columns the hypothesis names; not a test of it */
  relatedFindings: RelatedFinding[]
}
