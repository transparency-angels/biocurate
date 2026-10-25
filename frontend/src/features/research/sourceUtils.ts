import type { EvidenceType } from '@/types/research'

export interface ParsedPassage {
  pmcid: string | null
  anchor: string | null
  displayAnchor: string | null
  isEuropePmc: boolean
  isUpload: boolean
}

export function parsePassageAnchor(url: string | null): ParsedPassage {
  if (!url) {
    return { pmcid: null, anchor: null, displayAnchor: null, isEuropePmc: false, isUpload: false }
  }
  if (url.startsWith('upload://')) {
    const parts = url.split('#')
    const anchor = parts[1] ?? null
    return {
      pmcid: null,
      anchor,
      displayAnchor: anchor ? `#${anchor}` : null,
      isEuropePmc: false,
      isUpload: true,
    }
  }
  try {
    const parsed = new URL(url)
    const isEuropePmc = parsed.hostname.includes('europepmc.org')
    const pmcMatch = parsed.pathname.match(/\/PMC\/(PMC\w+)/i)
    const pmcid = pmcMatch ? pmcMatch[1] : null
    const hash = parsed.hash ? parsed.hash.replace(/^#/, '') : null
    const displayAnchor = hash
      ? pmcid
        ? `${pmcid}#${hash}`
        : `#${hash}`
      : pmcid
        ? `${pmcid}`
        : null
    return {
      pmcid,
      anchor: hash,
      displayAnchor,
      isEuropePmc,
      isUpload: false,
    }
  } catch {
    return { pmcid: null, anchor: null, displayAnchor: null, isEuropePmc: false, isUpload: false }
  }
}

export const EVIDENCE_TYPE_STYLES: Record<EvidenceType, { bg: string; text: string; border: string }> = {
  'Clinical study': {
    bg: 'bg-blue-500/10',
    text: 'text-blue-600 dark:text-blue-400',
    border: 'border-blue-500/30',
  },
  Dataset: {
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-600 dark:text-emerald-400',
    border: 'border-emerald-500/30',
  },
  Review: {
    bg: 'bg-purple-500/10',
    text: 'text-purple-600 dark:text-purple-400',
    border: 'border-purple-500/30',
  },
  'Experimental study': {
    bg: 'bg-cyan-500/10',
    text: 'text-cyan-600 dark:text-cyan-400',
    border: 'border-cyan-500/30',
  },
}
