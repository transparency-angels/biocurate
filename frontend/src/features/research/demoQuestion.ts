import { DEMO_SESSION_ID } from '@/data/mockHypotheses'

// The question lives in session storage so it survives a reload of the results page
// but not the end of the browser session. Storage can be blocked (private windows,
// strict privacy settings), so every access falls back to "no question".
const STORAGE_KEY = 'biocurate:demo-question'

export const DEMO_RESULTS_PATH = `/research/${DEMO_SESSION_ID}/results`
export const DEMO_PROGRESS_PATH = `/research/${DEMO_SESSION_ID}/progress`
export const DEMO_OVERVIEW_PATH = `/research/${DEMO_SESSION_ID}/overview`

export function readDemoQuestion(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function saveDemoQuestion(question: string) {
  try {
    sessionStorage.setItem(STORAGE_KEY, question)
  } catch {
    // The results page still loads; it just cannot show the question
  }
}

export function clearDemoQuestion() {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing stored, nothing to clear
  }
}
