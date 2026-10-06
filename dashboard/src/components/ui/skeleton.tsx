import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** Grey placeholder shown while data loads, shaped like the content that will appear. */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}