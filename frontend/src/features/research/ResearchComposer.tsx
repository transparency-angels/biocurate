import { useId, useLayoutEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import { ArrowUp, FileText, LoaderCircle, Plus, Settings2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_FORMATS_LABEL,
  addAttachments,
  formatBytes,
  type Attachment,
} from './attachments'
import type { SubmitResearch } from './types'

const MAX_TEXTAREA_HEIGHT = 240

const STARTERS = [
  { label: 'Explore research', prompt: 'What is currently known about ' },
  { label: 'Generate hypotheses', prompt: 'Generate testable hypotheses for ' },
  { label: 'Evaluate evidence', prompt: 'Evaluate the evidence that ' },
]

const isApplePlatform =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
const SUBMIT_SHORTCUT = isApplePlatform ? '⌘ + Enter' : 'Ctrl + Enter'

interface ResearchComposerProps {
  onSubmit: SubmitResearch
}

export function ResearchComposer({ onSubmit }: ResearchComposerProps) {
  const [question, setQuestion] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [problems, setProblems] = useState<string[]>([])
  const [pending, setPending] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [budgetUsd, setBudgetUsd] = useState(25)
  const [budgetTokens, setBudgetTokens] = useState(5_000_000)
  const [wallClockMinutes, setWallClockMinutes] = useState(10)
  const [initialHypotheses, setInitialHypotheses] = useState(3)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const ids = { label: useId(), hint: useId(), problems: useId() }

  const canSubmit = question.trim().length > 0 && !pending

  // Grow with the question up to a limit, then scroll inside the field
  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`
  }, [question])

  async function submit() {
    if (!canSubmit) return
    setPending(true)
    setProblems([])
    try {
      await onSubmit({
        question: question.trim(),
        files: attachments.map((a) => a.file),
        settings: { budgetUsd, budgetTokens, wallClockMinutes, initialHypotheses },
      })
      setQuestion('')
      setAttachments([])
    } catch (error) {
      setProblems([error instanceof Error ? error.message : 'Your question could not be submitted. Please try again.'])
    } finally {
      setPending(false)
      textareaRef.current?.focus()
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter alone inserts a new line; Ctrl/⌘ + Enter submits
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit()
    }
  }

  function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const result = addAttachments(attachments, Array.from(event.target.files ?? []))
    setAttachments(result.attachments)
    setProblems(result.problems)
    // Clear the input so the same file can be chosen again after removing it
    event.target.value = ''
  }

  function removeAttachment(attachment: Attachment) {
    setAttachments((current) => current.filter((a) => a.id !== attachment.id))
    setProblems([])
    textareaRef.current?.focus()
  }

  function applyStarter(prompt: string) {
    const current = STARTERS.find((starter) => question.startsWith(starter.prompt))
    const next = prompt + (current ? question.slice(current.prompt.length) : question)
    setQuestion(next)
    requestAnimationFrame(() => {
      const textarea = textareaRef.current
      if (!textarea) return
      textarea.focus()
      textarea.setSelectionRange(next.length, next.length)
    })
  }

  return (
    <div className="w-full">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
        className={cn(
          'rounded-3xl border border-border bg-card p-2.5 transition-[border-color,box-shadow] duration-200 ease-out',
          'hover:border-input focus-within:border-input focus-within:ring-4 focus-within:ring-ring/15',
        )}
      >
        {attachments.length > 0 && (
          <ul aria-label="Attached files" className="flex flex-wrap gap-2 px-1.5 pt-1 pb-2.5">
            {attachments.map((attachment) => (
              <li
                key={attachment.id}
                className="flex h-9 max-w-full items-center gap-2 rounded-xl bg-muted pr-1 pl-3 text-sm"
              >
                <FileText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate" title={attachment.file.name}>
                  {attachment.file.name}
                </span>
                <span className="shrink-0 text-xs text-faint tabular-nums">
                  {formatBytes(attachment.file.size)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  className="rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
                  aria-label={`Remove ${attachment.file.name}`}
                  onClick={() => removeAttachment(attachment)}
                >
                  <X />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="relative flex items-end gap-2">
          {settingsOpen && (
            <section aria-label="Co-Scientist run settings" className="absolute bottom-full left-0 z-20 mb-3 w-[min(26rem,calc(100vw-3rem))] rounded-2xl border border-border bg-popover p-4 text-popover-foreground shadow-xl ring-1 ring-black/5 sm:p-5">
              <div className="mb-4 flex items-start gap-3 border-b border-border pb-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-foreground"><Settings2 aria-hidden="true" className="size-4" /></span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold">Research settings</h2>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">Choose the limits for this research.</p>
                </div>
                <Button type="button" variant="ghost" size="icon-sm" className="-mr-1 -mt-1 rounded-full text-muted-foreground" aria-label="Close research settings" onClick={() => setSettingsOpen(false)}><X /></Button>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-4">
                <label className="space-y-1.5 text-xs font-medium text-foreground">
                  Spend limit (USD)
                  <input aria-label="Spend limit in US dollars" type="number" min={0.5} max={10000} step={0.5} value={budgetUsd} onChange={(event) => setBudgetUsd(Number(event.target.value))} className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground tabular-nums outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring/50" />
                </label>
                <label className="space-y-1.5 text-xs font-medium text-foreground">
                  Token cap
                  <input aria-label="Token cap" type="number" min={1000} max={100000000} step={1000} value={budgetTokens} onChange={(event) => setBudgetTokens(Number(event.target.value))} className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground tabular-nums outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring/50" />
                </label>
                <label className="space-y-1.5 text-xs font-medium text-foreground">
                  Time limit (minutes)
                  <input aria-label="Time limit in minutes" type="number" min={1} max={10080} step={1} value={wallClockMinutes} onChange={(event) => setWallClockMinutes(Number(event.target.value))} className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground tabular-nums outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring/50" />
                </label>
                <label className="space-y-1.5 text-xs font-medium text-foreground">
                  Initial hypotheses
                  <input aria-label="Initial hypothesis count" type="number" min={1} max={10} step={1} value={initialHypotheses} onChange={(event) => setInitialHypotheses(Number(event.target.value))} className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm font-normal text-foreground tabular-nums outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring/50" />
                </label>
              </div>
              <p className="mt-4 rounded-xl bg-muted/60 px-3 py-2.5 text-xs leading-5 text-muted-foreground">Spend is estimated from model usage. Token and time limits stop the run when reached.</p>
            </section>
          )}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            onChange={handleFiles}
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-lg"
            className="size-11 shrink-0 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground [&_svg:not([class*='size-'])]:size-5"
            aria-label="Attach research documents"
            title={`Attach ${ACCEPTED_FORMATS_LABEL} files or a ZIP archive`}
            disabled={pending}
            onClick={() => fileInputRef.current?.click()}
          >
            <Plus />
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon-lg"
            className="size-11 shrink-0 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground [&_svg:not([class*='size-'])]:size-[1.125rem]"
            aria-label="Research settings"
            aria-expanded={settingsOpen}
            aria-haspopup="dialog"
            title="Research settings"
            disabled={pending}
            onClick={() => setSettingsOpen((open) => !open)}
          >
            <Settings2 />
          </Button>

          <label id={ids.label} htmlFor={`${ids.label}-field`} className="sr-only">
            Research question
          </label>
          <textarea
            id={`${ids.label}-field`}
            ref={textareaRef}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="What scientific question would you like to explore?"
            aria-describedby={problems.length > 0 ? `${ids.hint} ${ids.problems}` : ids.hint}
            className={cn(
              'min-h-11 flex-1 resize-none bg-transparent py-2.5 text-base leading-6 text-foreground outline-none',
              'placeholder:text-faint',
            )}
          />

          <Button
            type="submit"
            size="icon-lg"
            className="size-11 shrink-0 rounded-full disabled:bg-muted disabled:text-faint disabled:opacity-100 [&_svg:not([class*='size-'])]:size-5"
            aria-label="Submit research question"
            disabled={!canSubmit}
          >
            {pending ? <LoaderCircle className="motion-safe:animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
      </form>

      <div role="alert" id={ids.problems} className="empty:hidden mt-3 space-y-1 px-4 text-sm text-destructive">
        {problems.map((problem) => (
          <p key={problem}>{problem}</p>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {STARTERS.map((starter) => (
          <Button
            key={starter.label}
            type="button"
            variant="secondary"
            className="h-9 rounded-full px-4 text-sm font-medium text-secondary-foreground"
            onClick={() => applyStarter(starter.prompt)}
          >
            {starter.label}
          </Button>
        ))}
      </div>

      {/* The exact attachment limits live on the attach button's tooltip rather than the hero */}
      <p id={ids.hint} className="mt-4 text-center text-[0.8125rem] leading-5 text-faint">
        Attach research files, or submit with <kbd className="font-sans">{SUBMIT_SHORTCUT}</kbd>.
      </p>
    </div>
  )
}
