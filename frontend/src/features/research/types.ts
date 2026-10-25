export interface ResearchSubmission {
  question: string
  files: File[]
  settings: ResearchRunSettings
}

export interface ResearchRunSettings {
  budgetUsd: number
  budgetTokens: number
  wallClockMinutes: number
  initialHypotheses: number
}

/**
 * Called when the user submits a research question.
 * Resolve to clear the composer; throw to keep its contents and show an error.
 */
export type SubmitResearch = (submission: ResearchSubmission) => void | Promise<void>
