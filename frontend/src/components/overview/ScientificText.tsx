import { Fragment, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import type { Citation } from '@/types/researchOverview'

/**
 * Renders the markdown the synthesis is written in, without a markdown library.
 *
 * The backend's prose uses a small, known subset — paragraphs, bullet and numbered
 * lists, bold, italic, backticked citation tags and inline TeX for Greek letters — and
 * the citation tags have to become interactive so a reader can jump to the source they
 * point at. A general renderer would still need custom handling for that, so the subset
 * is parsed here instead. Nothing is ever passed to `dangerouslySetInnerHTML`: every
 * node below is a React element, so backend text cannot inject markup or script.
 *
 * Anything outside the subset is shown as written rather than dropped.
 */

// ----------------------------- inline maths ----------------------------- //

/** TeX macros that appear in this backend's output, as their Unicode equivalents. */
const MATH_SYMBOLS: Record<string, string> = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', zeta: 'ζ', eta: 'η',
  theta: 'θ', iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π',
  rho: 'ρ', sigma: 'σ', tau: 'τ', upsilon: 'υ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Sigma: 'Σ', Phi: 'Φ', Omega: 'Ω',
  times: '×', pm: '±', mp: '∓', to: '→', rightarrow: '→', leftarrow: '←',
  leq: '≤', le: '≤', geq: '≥', ge: '≥', neq: '≠', approx: '≈', sim: '∼', cdot: '·',
  infty: '∞', degree: '°', prime: '′',
}

/**
 * Converts one `$…$` span to text. Known macros become their symbol, a lone `-/-`
 * becomes the superscript knockout notation, and an unknown macro keeps its name
 * rather than showing a stray backslash.
 */
function renderMath(source: string): string {
  let out = source.replace(/\\([A-Za-z]+)/g, (_, name: string) => MATH_SYMBOLS[name] ?? name)
  // Mouse-genetics knockout shorthand, e.g. Tlr2$-/-$
  out = out.replace(/(?:^|(?<=\s))-\/-(?=$|\s)/g, '⁻/⁻')
  // Spacing macros leave their braces behind
  return out.replace(/[{}]/g, '').replace(/\s+/g, ' ').trim()
}

// ----------------------------- citations ----------------------------- //

/** "S3, L5-L8" → a citation; anything else (e.g. a hypothesis id) → null. */
function parseCitationPart(part: string): Citation | null {
  const match = /^(S\d+)(?:\s*,\s*(L\d+(?:-L?\d+)?))?$/i.exec(part.trim())
  if (!match) return null
  return {
    raw: `[${match[1].toUpperCase()}${match[2] ? `, ${match[2]}` : ''}]`,
    sourceId: match[1].toUpperCase(),
    lineRange: match[2] ?? null,
  }
}

// Reference markers, not buttons: 50-odd of these sit inside the prose, so they are set
// as small type rather than filled pills, and carry no padding that would open a gap
// before the punctuation that follows them.
const markerClass = 'text-[0.8125em] leading-none font-medium whitespace-nowrap'

interface CitationTagProps {
  /** The text inside the brackets, e.g. "S3, L5-L8; S4, L4" or "H-hyp_…" */
  inner: string
  onCitationSelect?: (citation: Citation) => void
}

/**
 * One backticked tag. A tag can hold several citations separated by semicolons; each
 * becomes its own marker so every source is reachable on its own.
 */
function CitationTag({ inner, onCitationSelect }: CitationTagProps) {
  const parts = inner.split(';').map((part) => part.trim()).filter(Boolean)

  return (
    // Each marker stays unbroken, but a tag holding several may wrap between them
    <span>
      {parts.map((part, index) => {
        const separator = index > 0 ? <span className={markerClass}>, </span> : null
        const citation = parseCitationPart(part)
        if (!citation) {
          // A hypothesis id or anything else: shown as written, kept traceable
          return (
            <Fragment key={`${part}-${index}`}>
              {separator}
              <span className={cn(markerClass, 'break-all text-faint')}>{part}</span>
            </Fragment>
          )
        }
        const label = citation.lineRange ? `${citation.sourceId} ${citation.lineRange}` : citation.sourceId
        return (
          <Fragment key={`${part}-${index}`}>
            {separator}
            {onCitationSelect ? (
              <button
                type="button"
                onClick={() => onCitationSelect(citation)}
                title={`Go to source ${citation.sourceId}`}
                className={cn(
                  markerClass,
                  'rounded-sm font-medium text-brand underline decoration-brand/60 underline-offset-2 transition-colors outline-none',
                  'hover:decoration-brand focus-visible:ring-3 focus-visible:ring-ring/50',
                )}
              >
                {label}
                <span className="sr-only"> (go to this source)</span>
              </button>
            ) : (
              <span className={cn(markerClass, 'text-brand')}>{label}</span>
            )}
          </Fragment>
        )
      })}
    </span>
  )
}

// ----------------------------- inline parsing ----------------------------- //

interface InlineOptions {
  onCitationSelect?: (citation: Citation) => void
}

/** Splits a line into bold, italic, code, citation, maths and plain runs. */
function renderInline(line: string, options: InlineOptions, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let plain = ''
  let index = 0
  let key = 0

  const flush = () => {
    if (plain.length === 0) return
    nodes.push(<Fragment key={`${keyPrefix}-t${key++}`}>{plain}</Fragment>)
    plain = ''
  }
  /** Finds the matching closing marker, or -1 when the marker is unbalanced */
  const closingAt = (marker: string, from: number) => line.indexOf(marker, from)

  while (index < line.length) {
    const char = line[index]

    const bareUrl = /^https?:\/\/[^\s<>]+/i.exec(line.slice(index))
    if (bareUrl) {
      let href = bareUrl[0]
      let trailing = ''
      while (/[.,;:!?]$/.test(href)) {
        trailing = href.slice(-1) + trailing
        href = href.slice(0, -1)
      }
      // Closing punctuation belongs to the sentence unless it balances an opening
      // parenthesis that is part of the URL itself.
      while (href.endsWith(')') && (href.match(/\(/g)?.length ?? 0) < (href.match(/\)/g)?.length ?? 0)) {
        trailing = `)${trailing}`
        href = href.slice(0, -1)
      }
      try {
        const parsed = new URL(href)
        if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
          flush()
          nodes.push(<a key={`${keyPrefix}-u${key++}`} href={parsed.href} target="_blank" rel="noreferrer" className="break-all font-medium text-brand underline decoration-brand/60 underline-offset-[3px] hover:decoration-brand">{href}</a>)
          plain += trailing
          index += bareUrl[0].length
          continue
        }
      } catch { /* Invalid URLs remain visible as ordinary text. */ }
    }

    if (char === '[') {
      const labelEnd = line.indexOf('](', index + 1)
      const urlEnd = labelEnd >= 0 ? line.indexOf(')', labelEnd + 2) : -1
      if (labelEnd > index + 1 && urlEnd > labelEnd + 2) {
        const label = line.slice(index + 1, labelEnd)
        const href = line.slice(labelEnd + 2, urlEnd).trim()
        try {
          const parsed = new URL(href)
          if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
            flush()
            nodes.push(<a key={`${keyPrefix}-l${key++}`} href={parsed.href} target="_blank" rel="noreferrer" className="font-medium text-brand underline decoration-brand/60 underline-offset-[3px] hover:decoration-brand">{renderInline(label, options, `${keyPrefix}-link${key}`)}</a>)
            index = urlEnd + 1
            continue
          }
        } catch { /* Invalid or relative links remain visible as plain text. */ }
      }
    }

    if (char === '`') {
      const end = closingAt('`', index + 1)
      if (end === -1) { plain += char; index++; continue }
      const content = line.slice(index + 1, end)
      flush()
      const tag = /^\[(.+)\]$/.exec(content.trim())
      nodes.push(
        tag ? (
          <CitationTag key={`${keyPrefix}-c${key++}`} inner={tag[1]} onCitationSelect={options.onCitationSelect} />
        ) : (
          <code key={`${keyPrefix}-c${key++}`} className="rounded bg-secondary px-1 py-0.5 text-[0.875em]">
            {content}
          </code>
        ),
      )
      index = end + 1
      continue
    }

    if (char === '$') {
      const end = closingAt('$', index + 1)
      if (end === -1) { plain += char; index++; continue }
      flush()
      nodes.push(
        <span key={`${keyPrefix}-m${key++}`} className="whitespace-nowrap">
          {renderMath(line.slice(index + 1, end))}
        </span>,
      )
      index = end + 1
      continue
    }

    if (char === '*') {
      const strong = line.startsWith('**', index)
      const marker = strong ? '**' : '*'
      const end = closingAt(marker, index + marker.length)
      if (end === -1) { plain += char; index++; continue }
      const content = line.slice(index + marker.length, end)
      if (content.length === 0) { plain += char; index++; continue }
      flush()
      const inner = renderInline(content, options, `${keyPrefix}-${strong ? 's' : 'i'}${key}`)
      nodes.push(
        strong ? (
          <strong key={`${keyPrefix}-s${key++}`} className="font-semibold text-foreground">{inner}</strong>
        ) : (
          <em key={`${keyPrefix}-i${key++}`}>{inner}</em>
        ),
      )
      index = end + marker.length
      continue
    }

    plain += char
    index++
  }

  flush()
  return nodes
}

// ----------------------------- block parsing ----------------------------- //

interface ListItem {
  text: string
  /** Nesting level from the source indentation; shown as an indent, not a nested list */
  depth: number
}

type Block =
  | { kind: 'paragraph'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; items: ListItem[] }
  | { kind: 'table'; rows: string[][] }

const BULLET = /^([ \t]*)[-*][ \t]+(.*)$/
const ORDERED = /^([ \t]*)\d+[.)][ \t]+(.*)$/
const TABLE_ROW = /^\s*\|.*\|\s*$/
const TABLE_DIVIDER = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/

function tableCells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function parseBlocks(source: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }
  const lastList = (ordered: boolean) => {
    const last = blocks.at(-1)
    return last?.kind === 'list' && last.ordered === ordered ? last : null
  }

  const lines = source.split('\n')
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]
    if (line.trim().length === 0) { flushParagraph(); continue }

    if (TABLE_ROW.test(line) && index + 1 < lines.length && TABLE_DIVIDER.test(lines[index + 1])) {
      flushParagraph()
      const rows = [tableCells(line)]
      index += 2 // Consume the header and Markdown alignment row
      while (index < lines.length && TABLE_ROW.test(lines[index])) rows.push(tableCells(lines[index++]))
      index--
      blocks.push({ kind: 'table', rows })
      continue
    }

    const heading = /^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line)
    if (heading) {
      flushParagraph()
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] })
      continue
    }

    const ordered = ORDERED.exec(line)
    const bullet = ordered ? null : BULLET.exec(line)
    const match = ordered ?? bullet
    if (match) {
      flushParagraph()
      const isOrdered = ordered !== null
      const depth = Math.min(Math.floor(match[1].replace(/\t/g, '  ').length / 2), 3)
      const item: ListItem = { text: match[2].trim(), depth }
      const list = lastList(isOrdered)
      if (list) list.items.push(item)
      else blocks.push({ kind: 'list', ordered: isOrdered, items: [item] })
      continue
    }

    // A continuation line belongs to the list item above it
    const last = blocks.at(-1)
    if (paragraph.length === 0 && last?.kind === 'list' && last.items.length > 0) {
      const item = last.items[last.items.length - 1]
      item.text += ` ${line.trim()}`
      continue
    }
    paragraph.push(line.trim())
  }
  flushParagraph()
  return blocks
}

// ----------------------------- component ----------------------------- //

const INDENT = ['', 'ps-5', 'ps-10', 'ps-15'] as const

interface ScientificTextProps {
  children: string
  /** Called when a reader activates a `[S…]` citation chip */
  onCitationSelect?: (citation: Citation) => void
  /** `reading` sets the serif body used for long scientific prose */
  variant?: 'reading' | 'ui'
  className?: string
}

export function ScientificText({ children, onCitationSelect, variant = 'reading', className }: ScientificTextProps) {
  const blocks = parseBlocks(children)
  const options: InlineOptions = { onCitationSelect }
  const bodyClass =
    variant === 'reading'
      ? 'font-serif text-[1.0625rem] leading-[1.75] text-foreground/90'
      : 'text-[0.9375rem] leading-7 text-muted-foreground'

  return (
    <div className={cn('space-y-4', bodyClass, className)}>
      {blocks.map((block, blockIndex) => {
        if (block.kind === 'paragraph') {
          return <p key={blockIndex}>{renderInline(block.text, options, `b${blockIndex}`)}</p>
        }
        if (block.kind === 'heading') {
          const Heading = block.level <= 2 ? 'h3' : 'h4'
          return <Heading key={blockIndex} className="font-sans text-base font-semibold leading-6 text-foreground">{renderInline(block.text, options, `b${blockIndex}`)}</Heading>
        }
        if (block.kind === 'table') {
          const [header = [], ...rows] = block.rows
          return (
            <div key={blockIndex} className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[42rem] border-collapse text-left text-sm">
                <thead className="bg-muted/60 text-xs font-medium text-muted-foreground">
                  <tr>{header.map((cell, cellIndex) => <th key={cellIndex} scope="col" className="border-b border-border px-3 py-2.5">{renderInline(cell, options, `b${blockIndex}h${cellIndex}`)}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-border/70">
                  {rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="align-top hover:bg-muted/20">
                      {header.map((_, cellIndex) => <td key={cellIndex} className="px-3 py-2.5 text-foreground/85">{renderInline(row[cellIndex] ?? '', options, `b${blockIndex}r${rowIndex}c${cellIndex}`)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        const List = block.ordered ? 'ol' : 'ul'
        return (
          <List
            key={blockIndex}
            className={cn('space-y-2.5', block.ordered ? 'list-decimal' : 'list-disc', 'ps-5 marker:text-faint')}
          >
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex} className={cn('ps-1', INDENT[item.depth])}>
                {renderInline(item.text, options, `b${blockIndex}i${itemIndex}`)}
              </li>
            ))}
          </List>
        )
      })}
    </div>
  )
}
