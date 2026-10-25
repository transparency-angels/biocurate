export interface ResearchSubmission {
  question: string
  files: File[]
}

/**
 * Called when the user submits a research question.
 * Resolve to clear the composer; throw to keep its contents and show an error.
 */
export type SubmitResearch = (submission: ResearchSubmission) => void | Promise<void>
