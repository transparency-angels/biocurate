import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { DEMO_RESULTS_PATH } from '@/features/research/demoQuestion'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

interface NotFoundPageProps {
  title?: string
  message?: string
}

export function NotFoundPage({
  title = 'Page not found',
  message = 'The page you were looking for does not exist.',
}: NotFoundPageProps) {
  useDocumentTitle(title)

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">{title}</h1>
      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{message}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button asChild className="h-9 rounded-full px-4">
          <Link to="/">Go to home</Link>
        </Button>
        <Button asChild variant="outline" className="h-9 rounded-full px-4">
          <Link to={DEMO_RESULTS_PATH}>Open demo results</Link>
        </Button>
      </div>
    </div>
  )
}
