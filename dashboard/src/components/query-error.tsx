import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ApiError, describeError } from '@/lib/api'

/** Standard "could not load" box for a failed request, with the support reference. */
export function QueryError({ error, title = 'Could not load this' }: { error: unknown; title?: string }) {
  const forbidden = error instanceof ApiError && error.status === 403
  return (
    <Alert variant="destructive">
      <AlertTitle>{forbidden ? 'You do not have access to this' : title}</AlertTitle>
      <AlertDescription>
        {forbidden ? 'Ask an Owner of this company if you need access.' : describeError(error)}
      </AlertDescription>
    </Alert>
  )
}