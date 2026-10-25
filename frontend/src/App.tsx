import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router'
import { AppLayout } from '@/components/layout/AppLayout'
import type { SubmitResearch } from '@/features/research/types'
import type { HomeLocationState } from '@/features/research/useNewResearch'
import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ResearchOverview } from '@/pages/ResearchOverview'
import { ResearchProgress } from '@/pages/ResearchProgress'
import { ResearchResults } from '@/pages/ResearchResults'
import { ResearchData } from '@/pages/ResearchData'
import { ResearchWorkspace } from '@/pages/ResearchWorkspace'
import { createResearchSession } from '@/services/api'
import { rememberCurrentSession } from '@/features/research/currentSession'

function HomeRoute() {
  const navigate = useNavigate()
  const location = useLocation()
  const fresh = (location.state as HomeLocationState | null)?.fresh

  const submitResearch: SubmitResearch = async ({ question, files }) => {
    const trimmed = question.trim()
    if (!trimmed) return
    const sessionId = await createResearchSession(trimmed, files)
    rememberCurrentSession({ id: sessionId, savedAt: Date.now() })
    navigate(`/research/${sessionId}/chat`)
  }

  return <HomePage key={fresh ?? 'home'} onSubmitResearch={submitResearch} />
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomeRoute />} />
          <Route path="research/:sessionId/chat" element={<ResearchWorkspace />} />
          <Route path="research/:sessionId/progress" element={<ResearchProgress />} />
          <Route path="research/:sessionId/results" element={<ResearchResults />} />
          <Route path="research/:sessionId/data" element={<ResearchData />} />
          <Route path="research/:sessionId/overview" element={<ResearchOverview />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
