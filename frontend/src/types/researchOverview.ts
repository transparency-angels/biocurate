/**
 * The final research synthesis: the meta-review agent's consolidated report for a
 * session, which is a different thing from the ranked hypotheses in `research.ts`.
 *
 * The shapes below were read off a real synthesis export (`data/synthesis-2.json`).
 * Nothing in the Python backend in this repository emits this JSON yet — it writes the
 * same report as one markdown file (`co_scientist/agents/metareview.py`, template
 * `config/prompts/metareview_final.md`), whose headings match these fields one for one.
 * So treat the raw types as "whatever the exporter sends" and validate at the boundary.
 */

// ----------------------------- raw backend shapes ----------------------------- //
// Every field is optional: the adapter is the only place allowed to assume anything.

export interface RawCitation {
  /** The tag as it appears in the prose, e.g. "[S12, L2-L3]" */
  raw?: string | null
  source?: string | null
  source_id?: string | null
  source_tag?: string | null
  source_idx?: number | null
  start_line?: number | null
  end_line?: number | null
  line_range?: string | null
}

export interface RawExcerpt {
  line_range?: string | null
  start_line?: number | null
  end_line?: number | null
  text?: string | null
}

export interface RawSource {
  id?: string | null
  tag?: string | null
  index?: number | null
  title?: string | null
  url?: string | null
  /** Duplicate of `url` in the exports seen so far; used as a fallback */
  link?: string | null
  doi?: string | null
  year?: number | null
  line_range?: string | null
  summary_bullets?: (string | null)[] | null
  /** Repeat of `summary_bullets` in the exports seen so far */
  sub_bullets?: (string | null)[] | null
  raw_excerpt?: string | null
  excerpts?: RawExcerpt[] | null
  referenced_by?: (string | null)[] | null
}

export interface RawResearchDirection {
  id?: string | null
  index?: number | null
  title?: string | null
  claim?: string | null
  why_promising?: string | null
  open_questions?: string | null
  first_experiment?: string | null
  supporting_hypotheses?: (string | null)[] | null
  citations?: RawCitation[] | null
  /** The markdown the structured fields above were parsed out of */
  raw_markdown?: string | null
}

export interface RawOverview {
  session_id?: string | null
  generated_at?: string | null
  executive_summary?: string | null
  research_directions?: RawResearchDirection[] | null
  convergence_and_divergence?: string | null
  caveats_and_limitations?: string | null
  all_referenced_hypotheses?: (string | null)[] | null
  all_citations?: RawCitation[] | null
  /** The whole report as one markdown document; the structured fields cover it */
  markdown?: string | null
}

export interface RawSynthesis {
  session_id?: string | null
  generated_at?: string | null
  overview?: RawOverview | null
  sources?: { total_sources?: number | null; sources?: RawSource[] | null } | null
  /** Repeat of `sources.sources` at the top level in the exports seen so far */
  sources_list?: RawSource[] | null
}

// ----------------------------- view models ----------------------------- //

export interface Citation {
  /** The tag as written in the prose, e.g. "[S12, L2-L3]" */
  raw: string
  /** Source id, e.g. "S12". Matches `OverviewSource.id`. */
  sourceId: string
  /** e.g. "L2-L3", or null when the tag cites a whole source */
  lineRange: string | null
}

export interface SourceExcerpt {
  lineRange: string | null
  text: string
}

export interface OverviewSource {
  /** e.g. "S12" */
  id: string
  /** Position in the reference list; falls back to the order received */
  index: number
  title: string
  url: string | null
  doi: string | null
  year: number | null
  /** Short restatements of the source, as the exporter wrote them */
  bullets: string[]
  /** Verbatim quoted lines, keyed by the line range a citation can point at */
  excerpts: SourceExcerpt[]
  /** Hypothesis ids that cite this source */
  referencedBy: string[]
}

/**
 * One labelled part of a direction's open questions. The backend writes them as a
 * markdown list whose items start with a label ("What needs to be true:",
 * "What could falsify it:"); unlabelled prose keeps `label: null`.
 */
export interface OpenQuestionPart {
  label: string | null
  text: string
}

export interface ResearchDirection {
  id: string
  /** 1-based position used for the heading; falls back to the order received */
  index: number
  title: string
  claim: string | null
  whyPromising: string | null
  openQuestions: OpenQuestionPart[]
  firstExperiment: string | null
  supportingHypotheses: string[]
  citations: Citation[]
}

export interface ResearchOverview {
  sessionId: string | null
  /** ISO timestamp from the exporter, or null */
  generatedAt: string | null
  executiveSummary: string | null
  directions: ResearchDirection[]
  convergence: string | null
  caveats: string | null
  sources: OverviewSource[]
  /** Hypothesis ids the report refers to, across every section */
  referencedHypotheses: string[]
}
