import { SearchX } from 'lucide-react'
import { Link } from 'react-router'

import { EmptyState } from '@/components/empty-state'
import { Button } from '@/components/ui/button'

export function NotFoundContent({ what = 'Page' }: { what?: string }) {
  return (
    <EmptyState
      icon={SearchX}
      title={`${what} not found`}
      description="It does not exist, or you do not have access to it."
      action={
        <Button asChild variant="outline">
          <Link to="/">Back to your companies</Link>
        </Button>
      }
    />
  )
}

export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-full max-w-lg items-center px-4">
      <div className="w-full">
        <NotFoundContent />
      </div>
    </div>
  )
}