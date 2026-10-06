import { Link } from 'react-router'

import { cn } from '@/lib/utils'

export function Brand({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn('flex items-center gap-2 font-semibold tracking-tight', className)}>
      <span className="grid size-7 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">Z</span>
      <span>ZipZy DBA</span>
    </Link>
  )
}