import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { FileText } from 'lucide-react'
import { ResearchViewSwitch } from '@/components/research/ResearchViewSwitch'
import { ScientificText } from '@/components/overview/ScientificText'
import { formatBytes } from '@/features/research/attachments'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { ApiError, getAnalysis, getAttachments, getSession, type AnalysisReport, type AttachmentRecord, type SessionSnapshot } from '@/services/api'
import { NotFoundPage } from './NotFoundPage'

export function ResearchData() {
  const { sessionId = '' } = useParams()
  const [analysis, setAnalysis] = useState<AnalysisReport | null>(null)
  const [attachments, setAttachments] = useState<AttachmentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sessionStatus, setSessionStatus] = useState<SessionSnapshot['status'] | null>(null)

  const refresh = useCallback(() => Promise.all([getSession(sessionId), getAttachments(sessionId), getAnalysis(sessionId).catch((e: Error) => {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    })])
      .then(([session, attached, report]) => {
        setSessionStatus(session.status)
        setAnalysis(report)
        setAttachments(attached.attachments)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false)), [sessionId])
  useEffect(() => {
    let active = true
    const load = () => { if (active) void refresh() }
    load()
    const timer = sessionStatus === null || sessionStatus === 'running' ? window.setInterval(load, 4000) : undefined
    return () => { active = false; if (timer !== undefined) window.clearInterval(timer) }
  }, [refresh, sessionStatus])
  useDocumentTitle('Dataset analysis')

  if (error && sessionStatus === null) return <NotFoundPage title="Dataset analysis unavailable" message={error} />
  return (
    <div className="mx-auto w-full max-w-[76rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ResearchViewSwitch sessionId={sessionId} />
      <div className="mt-5"><h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Dataset analysis</h1><p className="mt-1 text-sm leading-6 text-muted-foreground">Analysis and files attached to this research session.</p></div>
      {error && <p role="status" className="mt-4 text-sm text-muted-foreground">Could not refresh just now. Showing the latest saved analysis.</p>}

      {attachments.length > 0 && (
        <section aria-labelledby="attached-files-title" className="mt-6 rounded-xl border border-border bg-card">
          <div className="border-b border-border px-5 py-3.5 sm:px-6"><h2 id="attached-files-title" className="text-sm font-semibold text-foreground">Attached files</h2></div>
          <ul className="divide-y divide-border">
            {attachments.map((file) => <li key={file.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 sm:px-6"><span className="flex min-w-0 items-center gap-2 text-sm text-foreground"><FileText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /><span className="truncate">{file.filename}</span></span><span className="text-xs text-muted-foreground">{file.kind === 'tabular' ? 'Dataset' : 'Document'} · {formatBytes(file.size)} · {file.status}</span></li>)}
          </ul>
        </section>
      )}

      {loading ? <p className="mt-8 text-sm text-muted-foreground">Loading dataset analysis…</p> : !analysis ? (
        <section className="mt-6 rounded-xl border border-border bg-card px-5 py-6 sm:px-6">
          <h2 className="text-sm font-semibold text-foreground">No dataset analysis available</h2>
          <p className="mt-1.5 max-w-[68ch] text-sm leading-6 text-muted-foreground">{sessionStatus === 'running' || sessionStatus === 'paused' ? 'Dataset profiling is still in progress. This page refreshes automatically when the report is ready.' : 'No analysis report was saved for this session. Check the attached file statuses above; supported CSV, TSV, and delimited TXT tables are analysed automatically when the research starts.'}</p>
        </section>
      ) : (
        <div className="mt-6 space-y-6">
          <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-6">
            <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
              {analysis.sample_count !== undefined && <p><span className="text-muted-foreground">{analysis.profile_type === 'exploratory_tabular' ? 'Rows profiled' : 'Samples'}</span><span className="ml-2 font-medium tabular-nums text-foreground">{analysis.sample_count}</span></p>}
              {(analysis.group_comparisons || analysis.candidates) && <p><span className="text-muted-foreground">{analysis.profile_type === 'exploratory_tabular' ? 'Group comparisons' : 'Candidate associations'}</span><span className="ml-2 font-medium tabular-nums text-foreground">{analysis.profile_type === 'exploratory_tabular' ? analysis.group_comparisons_total ?? analysis.selection?.group_comparisons ?? analysis.group_comparisons?.length ?? 0 : analysis.candidates?.length ?? 0}</span></p>}
              {analysis.generated_at && <p><span className="text-muted-foreground">Completed</span><time className="ml-2 text-foreground" dateTime={analysis.generated_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(analysis.generated_at))}</time></p>}
            </div>
          </section>

          {analysis.summary_markdown && <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-6"><ScientificText>{analysis.summary_markdown}</ScientificText></section>}
          {analysis.plots && analysis.plots.length > 0 && <section className="space-y-4"><h2 className="text-base font-semibold text-foreground">Analysis plots</h2><div className="grid gap-4 lg:grid-cols-2">{analysis.plots.map((plot) => <figure key={plot.name} className="overflow-hidden rounded-xl border border-border bg-card p-3"><img src={plot.url} alt={`Dataset analysis plot: ${plot.name.replaceAll('_', ' ')}`} loading="lazy" className="h-auto w-full" /><figcaption className="px-2 pt-2 text-sm text-muted-foreground">{plot.name.replaceAll('_', ' ')}</figcaption></figure>)}</div></section>}
        </div>
      )}
    </div>
  )
}
