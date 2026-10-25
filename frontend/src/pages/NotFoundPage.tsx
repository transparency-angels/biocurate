import { Link } from 'react-router'
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
      <Link className="mt-6 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground" to="/">Go to home</Link>
    </div>
  )
}
