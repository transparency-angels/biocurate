import type {
  Citation,
  OpenQuestionPart,
  OverviewSource,
  RawCitation,
  RawOverview,
  RawResearchDirection,
  RawSource,
  RawSynthesis,
  ResearchDirection,
  ResearchOverview,
  SourceExcerpt,
} from '@/types/researchOverview'

/**
 * Turns a raw synthesis export into the view model the overview page renders.
 *
 * Everything the exporter sends is treated as untrusted: missing fields, nulls, empty
 * arrays and a directions list of any length (including none) all have to come out as a
 * renderable object. Nothing is invented — a field the backend did not send stays null,
 * and the page shows that it is absent.
 */

const text = (value: unknown): string | null => {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.flatMap((item) => (text(item) !== null ? [text(item) as string] : [])) : []

const integer = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

/** "[S12, L2-L3]" or "[S3]" → its parts. Returns null for anything else, e.g. "[H-hyp_…]". */
function parseCitationTag(raw: string): Citation | null {
  const match = /^\[\s*(S\d+)\s*(?:,\s*(L[\d\s-]*\d))?\s*\]$/i.exec(raw.trim())
  if (!match) return null
  return { raw: raw.trim(), sourceId: match[1].toUpperCase(), lineRange: match[2]?.replace(/\s+/g, '') ?? null }
}

function toCitation(raw: RawCitation): Citation | null {
  const sourceId = text(raw.source_id) ?? text(raw.source)
  if (sourceId === null) {
    // No id field: fall back to reading the tag itself
    const tag = text(raw.raw) ?? text(raw.source_tag)
    return tag === null ? null : parseCitationTag(tag)
  }
  const lineRange = text(raw.line_range)
  return {
    raw: text(raw.raw) ?? `[${sourceId}${lineRange ? `, ${lineRange}` : ''}]`,
    sourceId: sourceId.toUpperCase(),
    lineRange,
  }
}

/** Keeps the first mention of each tag, so a section's citation list reads once per source. */
function uniqueCitations(raws: RawCitation[] | null | undefined): Citation[] {
  const seen = new Set<string>()
  const out: Citation[] = []
  for (const raw of raws ?? []) {
    const citation = toCitation(raw)
    if (!citation) continue
    const key = `${citation.sourceId}|${citation.lineRange ?? ''}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(citation)
  }
  return out
}

function toExcerpts(raw: RawSource): SourceExcerpt[] {
  const excerpts = (raw.excerpts ?? []).flatMap((excerpt): SourceExcerpt[] => {
    const body = text(excerpt?.text)
    return body === null ? [] : [{ lineRange: text(excerpt?.line_range), text: body }]
  })
  if (excerpts.length > 0) return excerpts
  // Older exports carry one blob instead of a list
  const fallback = text(raw.raw_excerpt)
  return fallback === null ? [] : [{ lineRange: text(raw.line_range), text: fallback }]
}

function toSource(raw: RawSource, position: number): OverviewSource | null {
  const id = text(raw.id) ?? text(raw.tag)?.replace(/[[\]]/g, '') ?? null
  if (id === null) return null
  const bullets = strings(raw.summary_bullets)
  return {
    id: id.toUpperCase(),
    index: integer(raw.index) ?? position + 1,
    // A source with no title still has to be citable, so it falls back to its id
    title: text(raw.title) ?? id,
    url: text(raw.url) ?? text(raw.link),
    doi: text(raw.doi),
    year: integer(raw.year),
    bullets: bullets.length > 0 ? bullets : strings(raw.sub_bullets),
    excerpts: toExcerpts(raw),
    referencedBy: strings(raw.referenced_by),
  }
}

/**
 * Splits the open-questions markdown into its labelled parts.
 *
 * The backend writes a list whose items open with an italic label, as the prompt asks
 * ("What would need to be true…? What could falsify it?"):
 *
 *   - *What needs to be true:* …
 *   - *What could falsify it:* …
 *
 * Anything that does not match that shape is kept whole, with no label.
 */
export function splitOpenQuestions(body: string | null): OpenQuestionPart[] {
  if (body === null) return []
  const parts: OpenQuestionPart[] = []
  // Each item starts on its own line with a bullet; labels are *…:* or **…:**
  const itemPattern = /^[ \t]*[-*][ \t]+(?:\*{1,2}([^*]+?)\*{1,2}[ \t]*)?/
  let current: OpenQuestionPart | null = null

  for (const line of body.split('\n')) {
    const match = itemPattern.exec(line)
    if (match) {
      if (current) parts.push(current)
      const label = match[1]?.trim().replace(/[:.]$/, '') ?? null
      current = { label, text: line.slice(match[0].length).trim() }
    } else if (current) {
      const continued = line.trim()
      if (continued.length > 0) current.text += `\n${continued}`
    } else {
      const opening = line.trim()
      if (opening.length > 0) current = { label: null, text: opening }
    }
  }
  if (current) parts.push(current)

  const meaningful = parts.filter((part) => part.text.length > 0 || part.label !== null)
  return meaningful.length > 0 ? meaningful : [{ label: null, text: body }]
}

function toDirection(raw: RawResearchDirection, position: number): ResearchDirection | null {
  const title = text(raw.title)
  const claim = text(raw.claim)
  // A direction with neither a name nor a claim has nothing to show
  if (title === null && claim === null) return null
  return {
    id: text(raw.id) ?? `direction-${position + 1}`,
    index: integer(raw.index) ?? position + 1,
    title: title ?? `Direction ${position + 1}`,
    claim,
    whyPromising: text(raw.why_promising),
    openQuestions: splitOpenQuestions(text(raw.open_questions)),
    firstExperiment: text(raw.first_experiment),
    supportingHypotheses: strings(raw.supporting_hypotheses),
    citations: uniqueCitations(raw.citations),
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

/**
 * Normalises a synthesis export. Returns null when the payload carries no report at all,
 * so the caller can show an empty state instead of a blank page.
 */
export function normaliseSynthesis(payload: unknown): ResearchOverview | null {
  if (!isRecord(payload)) return null
  const raw = payload as RawSynthesis
  const overview: RawOverview = isRecord(raw.overview) ? raw.overview : {}

  const rawSources = raw.sources?.sources ?? raw.sources_list ?? []
  const sources: OverviewSource[] = []
  const seenSources = new Set<string>()
  for (const [position, entry] of rawSources.entries()) {
    const source = isRecord(entry) ? toSource(entry, position) : null
    // The same source is exported twice in some payloads; the first wins
    if (!source || seenSources.has(source.id)) continue
    seenSources.add(source.id)
    sources.push(source)
  }

  const directions = (overview.research_directions ?? []).flatMap((entry, position) => {
    const direction = isRecord(entry) ? toDirection(entry, position) : null
    return direction ? [direction] : []
  })

  const result: ResearchOverview = {
    sessionId: text(overview.session_id) ?? text(raw.session_id),
    generatedAt: text(overview.generated_at) ?? text(raw.generated_at),
    executiveSummary: text(overview.executive_summary),
    directions,
    convergence: text(overview.convergence_and_divergence),
    caveats: text(overview.caveats_and_limitations),
    sources: sources.sort((a, b) => a.index - b.index),
    referencedHypotheses: strings(overview.all_referenced_hypotheses),
  }

  const hasContent =
    result.executiveSummary !== null ||
    result.directions.length > 0 ||
    result.convergence !== null ||
    result.caveats !== null ||
    result.sources.length > 0
  return hasContent ? result : null
}

/** Index of sources by id, for resolving a citation tag to the source it points at. */
export function sourcesById(sources: OverviewSource[]): Map<string, OverviewSource> {
  return new Map(sources.map((source) => [source.id, source]))
}
