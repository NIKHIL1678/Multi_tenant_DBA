import { cn } from '@/lib/utils'

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn('inline-block size-5 animate-spin rounded-full border-2 border-primary border-t-transparent', className)}
    />
  )
}

export function FullPageSpinner() {
  return (
    <div className="flex h-full min-h-48 items-center justify-center">
      <Spinner className="size-6" />
    </div>
  )
}