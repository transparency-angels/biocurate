import { useCallback } from 'react'
import { useNavigate } from 'react-router'
import { clearDemoQuestion } from './demoQuestion'

export interface HomeLocationState {
  /** Changes on every "New research", so the home page remounts with an empty composer */
  fresh?: number
}

/** Clears the temporary demo question and returns to an empty research prompt. */
export function useNewResearch() {
  const navigate = useNavigate()

  return useCallback(() => {
    clearDemoQuestion()
    navigate('/', { state: { fresh: Date.now() } satisfies HomeLocationState })
  }, [navigate])
}
