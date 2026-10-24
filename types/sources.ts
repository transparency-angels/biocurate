/**
 * TypeScript interface definitions for scientific literature sources
 * synthesized during co-scientist research sessions.
 *
 * Merges source references from the overview with verbatim line-numbered
 * excerpts in a unified JSON structure for seamless rendering in React frameworks.
 */

/**
 * Individual verbatim excerpt extracted from a scientific source document.
 */
export interface SourceExcerpt {
  /** Relative line range in the excerpt/document, e.g. "L1-L8" */
  line_range?: string | null;
  /** 1-based start line number if available */
  start_line?: number | null;
  /** 1-based end line number if available */
  end_line?: number | null;
  /** Verbatim excerpt text extracted from the paper */
  text: string;
}

/**
 * Unified scientific source item merging overview references with raw literature excerpts.
 */
export interface SourceItem {
  /** Source identifier, e.g. "S1" */
  id: string;
  /** Citation tag as referenced inline, e.g. "[S1]" */
  tag: string;
  /** Numeric source index (1-based) */
  index: number;
  /** Paper or article title */
  title: string;
  /** Full URL to the source (e.g. PubMed or PMC link) */
  url: string;
  /** Link alias for url */
  link: string;
  /** Digital Object Identifier (DOI), if available */
  doi: string | null;
  /** Publication year, if available */
  year: number | null;
  /** Consolidated line range across excerpts, e.g. "L1-L15" */
  line_range: string | null;
  /** 2-3 concise summary bullet points describing key mechanisms/findings */
  summary_bullets: string[];
  /** Sub-bullet alias for summary_bullets */
  sub_bullets: string[];
  /** Full raw verbatim excerpt text */
  raw_excerpt?: string | null;
  /** Detailed verbatim excerpts extracted from this source */
  excerpts: SourceExcerpt[];
  /** Hypothesis IDs or review IDs that cite or are supported by this source */
  referenced_by: string[];
}

/**
 * Complete sources artifact payload for React components.
 */
export interface SourcesData {
  session_id: string;
  generated_at: string;
  total_sources: number;
  sources: SourceItem[];
}

export type SourceList = SourceItem[];

