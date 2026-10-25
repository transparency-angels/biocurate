import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUp, Bot, LoaderCircle, MessageCircle, Sparkles } from 'lucide-react'
import { ScientificText } from '@/components/overview/ScientificText'
import { Button } from '@/components/ui/button'
import { getCachedChatHistory, getChatHistory, sendChatMessage, type SessionSnapshot, type TimelineMessage } from '@/services/api'

const STARTERS = [
  'What is the strongest evidence so far?',
  'What are the main uncertainties?',
  'How could we test the leading hypothesis?',
]

export function ResearchChat({ sessionId, sessionStatus }: { sessionId: string; sessionStatus: SessionSnapshot['status'] }) {
  const [messages, setMessages] = useState<TimelineMessage[]>(() => getCachedChatHistory(sessionId)?.messages ?? [])
  const [draft, setDraft] = useState('')
  const [guideResearch, setGuideResearch] = useState(false)
  const [sending, setSending] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(() => getCachedChatHistory(sessionId) !== undefined)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const canGuideResearch = sessionStatus === 'running' || sessionStatus === 'paused'

  useEffect(() => {
    let active = true
    void getChatHistory(sessionId)
      .then(({ messages: history }) => { if (active) setMessages(history) })
      .catch(() => { if (active) setError('The conversation could not be loaded. Refresh to try again.') })
      .finally(() => { if (active) setHistoryLoaded(true) })
    return () => { active = false }
  }, [sessionId])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, sending])

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    const question = draft.trim()
    if (!question || sending) return
    setSending(true)
    setError(null)
    setDraft('')
    try {
      const result = await sendChatMessage(sessionId, question, guideResearch && canGuideResearch)
      setMessages((current) => [...current, ...result.messages])
    } catch (cause) {
      setDraft(question)
      setError(cause instanceof Error ? cause.message : 'The message could not be sent.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section aria-labelledby="research-chat-title" className="flex min-h-[34rem] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm lg:min-h-[min(68dvh,54rem)]">
      <header className="flex items-center gap-3 border-b border-border px-5 py-4 sm:px-6">
        <span className="flex size-9 items-center justify-center rounded-xl bg-brand/10 text-brand"><MessageCircle aria-hidden="true" className="size-[1.125rem]" /></span>
        <div className="min-w-0"><h2 id="research-chat-title" className="text-sm font-semibold text-foreground">Research conversation</h2><p className="mt-0.5 text-xs text-muted-foreground">Grounded in this session’s saved findings</p></div>
      </header>

      <div aria-live="polite" className="flex-1 space-y-5 overflow-y-auto px-4 py-5 sm:px-6">
        {messages.length === 0 ? (
          <div className="flex min-h-[23rem] flex-col items-center justify-center text-center">
            <span className="flex size-11 items-center justify-center rounded-2xl border border-brand/15 bg-brand/[0.05] text-brand"><Sparkles aria-hidden="true" className="size-5" /></span>
            <h3 className="mt-4 text-base font-semibold text-foreground">Stay with the question</h3>
            <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">Ask about evidence, compare hypotheses, or decide what to investigate next. This conversation is saved with your research.</p>
            <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
              {STARTERS.map((starter) => <button key={starter} type="button" onClick={() => setDraft(starter)} className="rounded-full border border-border bg-background px-3 py-2 text-xs text-muted-foreground transition-colors hover:border-brand/30 hover:text-foreground">{starter}</button>)}
            </div>
          </div>
        ) : messages.map((message) => (
          <article key={message.seq} className={message.role === 'user' ? 'ml-auto max-w-[88%]' : 'mr-auto max-w-[96%]'}>
            <div className={`mb-1.5 flex items-center gap-2 text-[0.7rem] ${message.role === 'user' ? 'justify-end text-muted-foreground' : 'text-muted-foreground'}`}>
              {message.role === 'assistant' && <Bot aria-hidden="true" className="size-3.5 text-brand" />}
              <span>{message.title}</span>
              <time dateTime={new Date(message.ts).toISOString()}>{new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(message.ts)}</time>
            </div>
            <div className={message.role === 'user' ? 'rounded-2xl rounded-tr-sm bg-brand px-4 py-3 text-sm leading-6 text-white' : 'rounded-2xl rounded-tl-sm bg-muted/55 px-4 py-3.5 sm:px-5'}>
              {message.role === 'user' ? <p className="whitespace-pre-wrap">{message.body_markdown}</p> : <ScientificText variant="ui" className="text-foreground/90">{message.body_markdown}</ScientificText>}
            </div>
          </article>
        ))}
        {sending && <div className="mr-auto flex items-center gap-2 rounded-xl bg-muted/55 px-4 py-3 text-xs text-muted-foreground"><LoaderCircle aria-hidden="true" className="size-4 animate-spin text-brand" />Thinking through the saved research…</div>}
        <div ref={endRef} />
      </div>

      <form onSubmit={(event) => void submit(event)} className="border-t border-border bg-background/70 p-3 sm:p-4">
        {error && <p role="alert" className="mb-2 px-2 text-xs text-destructive">{error}</p>}
        <div className="rounded-2xl border border-input bg-card shadow-sm focus-within:border-brand/45 focus-within:ring-3 focus-within:ring-brand/10">
          <label htmlFor="research-chat-message" className="sr-only">Ask about this research</label>
          <textarea id="research-chat-message" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} rows={2} maxLength={4000} placeholder="Ask a question about this research…" className="block w-full resize-y bg-transparent px-4 pt-3.5 text-sm leading-6 text-foreground outline-none placeholder:text-faint" />
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2.5 pt-1">
            <label title={canGuideResearch ? undefined : 'This research session has stopped accepting new directions.'} className={`flex select-none items-center gap-2 px-1 text-xs ${canGuideResearch ? 'cursor-pointer text-muted-foreground' : 'cursor-not-allowed text-faint'}`}><input type="checkbox" checked={guideResearch && canGuideResearch} disabled={!canGuideResearch} onChange={(event) => setGuideResearch(event.target.checked)} className="size-3.5 accent-[var(--brand)]" />Also use this as guidance for future research</label>
            <Button type="submit" disabled={!draft.trim() || sending || !historyLoaded} aria-label="Send message" className="size-8 rounded-full bg-brand text-white hover:bg-brand/90"><ArrowUp aria-hidden="true" className="size-4" /></Button>
          </div>
        </div>
        <p className="mt-2 px-1 text-[0.6875rem] text-faint">Saved findings may be incomplete. Verify important claims against the cited sources.</p>
      </form>
    </section>
  )
}
