import { useCallback } from 'react'
import { useNavigate } from 'react-router'

export interface HomeLocationState {
  /** Changes on every "New research", so the home page remounts with an empty composer */
  fresh?: number
}

/** Returns to an empty research prompt. */
export function useNewResearch() {
  const navigate = useNavigate()

  return useCallback(() => {
    navigate('/', { state: { fresh: Date.now() } satisfies HomeLocationState })
  }, [navigate])
}
