import type { DataPoint, DataVerdict } from '@/types/research'

export const formatValue = (value: number) =>
  value.toLocaleString('en', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** p and q values the way papers print them: three significant figures, floored at 0.001. */
export function formatP(value: number | null) {
  if (value === null) return '–'
  if (value < 0.001) return '< 0.001'
  return value.toPrecision(value < 0.01 ? 2 : 3).replace(/\.?0+$/, '')
}

export const formatCount = (value: number) => value.toLocaleString('en')

/** What each verdict means, in one plain sentence. */
export const VERDICT_COPY: Record<DataVerdict, { label: string; meaning: string }> = {
  supported: {
    label: 'Supported by your data',
    meaning: 'The effect holds after correcting for every comparison tested in this dataset.',
  },
  nominal: {
    label: 'Weak support',
    meaning: 'Significant on its own, but not after correcting for the number of comparisons tested.',
  },
  not_significant: {
    label: 'Not supported',
    meaning: 'The data was tested and showed no clear effect.',
  },
  not_tested: {
    label: 'Not tested against your data',
    meaning: 'No analysed comparison in this session matches this hypothesis.',
  },
}

/** Sample rows as CSV, so the values can be re-analysed elsewhere. */
export function pointsCsv(points: DataPoint[], unit: string) {
  const escape = (text: string) => (/[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text)
  const rows = points.map((point) =>
    [escape(point.label), escape(point.group), String(point.value),
      point.event === null ? '' : point.event ? '1' : '0'].join(','),
  )
  return [`sample,group,time_${unit || 'value'},event`, ...rows].join('\n')
}
