import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 px-4 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
        Go home
      </Link>
    </div>
  )
}