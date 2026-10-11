import type { ReactNode } from 'react'

import { Card, CardContent } from '@/components/ui/card'

/** The frame of every page you see before (or while) signing in: logo, title, one card. */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="flex min-h-full items-center justify-center bg-muted/40 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-primary text-lg font-bold text-primary-foreground">
            Z
          </span>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        <Card>
          <CardContent className="min-w-0 pt-6">{children}</CardContent>
        </Card>
        {footer && <div className="mt-6 text-center text-sm text-muted-foreground">{footer}</div>}
      </div>
    </div>
  )
}