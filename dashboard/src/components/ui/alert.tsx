import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

const alertVariants = cva('grid gap-1 rounded-lg border px-4 py-3 text-sm [&>svg]:size-4', {
  variants: {
    variant: {
      default: 'bg-card text-card-foreground',
      destructive: 'border-destructive/30 bg-danger-soft text-destructive',
      warning: 'border-warning/30 bg-warning-soft text-warning',
    },
  },
  defaultVariants: { variant: 'default' },
})

export function Alert({ className, variant, ...props }: ComponentProps<'div'> & VariantProps<typeof alertVariants>) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
}

export function AlertTitle({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('font-medium', className)} {...props} />
}

export function AlertDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('opacity-90', className)} {...props} />
}