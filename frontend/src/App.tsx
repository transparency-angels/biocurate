import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router'
import { AppLayout } from '@/components/layout/AppLayout'
import { DEMO_PROGRESS_PATH, saveDemoQuestion } from '@/features/research/demoQuestion'
import type { SubmitResearch } from '@/features/research/types'
import type { HomeLocationState } from '@/features/research/useNewResearch'
import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ResearchOverview } from '@/pages/ResearchOverview'
import { ResearchProgress } from '@/pages/ResearchProgress'
import { ResearchResults } from '@/pages/ResearchResults'
import { clearDemoSimulation } from '@/services/mockEventSource'

// Integration point for the Co-Scientist backend. Nothing is sent to it yet: a
// submission stores the question and starts a fresh demo simulation on the progress
// page. Attached files are not used until the backend can receive them.
function HomeRoute() {
  const navigate = useNavigate()
  const location = useLocation()
  const fresh = (location.state as HomeLocationState | null)?.fresh

  const submitResearch: SubmitResearch = ({ question }) => {
    const trimmed = question.trim()
    if (!trimmed) return
    saveDemoQuestion(trimmed)
    clearDemoSimulation()
    navigate(DEMO_PROGRESS_PATH)
  }

  return <HomePage key={fresh ?? 'home'} onSubmitResearch={submitResearch} />
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomeRoute />} />
          <Route path="research/:sessionId/progress" element={<ResearchProgress />} />
          <Route path="research/:sessionId/results" element={<ResearchResults />} />
          <Route path="research/:sessionId/overview" element={<ResearchOverview />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
