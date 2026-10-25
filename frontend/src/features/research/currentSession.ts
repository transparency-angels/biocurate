const STORAGE_KEY = 'biocurate:current-session-id'
const UPDATED_EVENT = 'biocurate:current-session-updated'

export interface CurrentSession {
  id: string
  savedAt: number
  question?: string
}

export function readCurrentSession(): CurrentSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<CurrentSession>
    if (typeof value.id !== 'string') return null
    return { id: value.id, savedAt: typeof value.savedAt === 'number' ? value.savedAt : 0 }
  } catch {
    return null
  }
}

export function rememberCurrentSession(session: CurrentSession) {
  try {
    localStorage.removeItem('biocurate:current-session')
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    window.dispatchEvent(new Event(UPDATED_EVENT))
  } catch {
    // The active route still works if browser storage is unavailable.
  }
}

export function clearCurrentSession() {
  try {
    localStorage.removeItem(STORAGE_KEY)
    window.dispatchEvent(new Event(UPDATED_EVENT))
  } catch {
    // The active route still works if browser storage is unavailable.
  }
}

export function subscribeCurrentSession(listener: () => void) {
  window.addEventListener(UPDATED_EVENT, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(UPDATED_EVENT, listener)
    window.removeEventListener('storage', listener)
  }
}
