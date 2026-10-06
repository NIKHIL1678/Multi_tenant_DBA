import { Tabs as TabsPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export const Tabs = TabsPrimitive.Root

/** Underlined tab bar. Scrolls sideways on narrow screens instead of wrapping. */
export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn('-mx-4 mb-5 flex gap-1 overflow-x-auto border-b px-4 sm:mx-0 sm:px-0', className)}
      {...props}
    />
  )
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        '-mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none',
        'hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50',
        'data-[state=active]:border-primary data-[state=active]:text-foreground',
        className,
      )}
      {...props}
    />
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn('outline-none', className)} {...props} />
}

/** Small number next to a tab label. */
export function TabCount({ children }: { children: number | undefined }) {
  if (children === undefined) return null
  return <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground">{children}</span>
}