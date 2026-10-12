import type { LucideIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/** One number on the overview, e.g. "Connections 42 / 151". */
export function Metric({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: ReactNode
  detail?: ReactNode
  tone?: 'warning'
}) {
  return (
    <div className={cn('rounded-xl border bg-card p-3 shadow-xs sm:p-4', tone === 'warning' && 'border-warning/40')}>
      <p className="truncate text-xs text-muted-foreground sm:text-sm">{label}</p>
      <p className={cn('mt-1 text-xl font-semibold tabular-nums sm:text-2xl', tone === 'warning' && 'text-warning')}>
        {value ?? '—'}
      </p>
      {detail && <p className="mt-0.5 truncate text-xs text-muted-foreground">{detail}</p>}
    </div>
  )
}

const FIRST_ROWS = 5 // longer finding lists open with "Show all"

/** A titled block of findings with a count and one line on why it matters. */
export function FindingSection({
  icon: Icon,
  title,
  count,
  why,
  children,
}: {
  icon: LucideIcon
  title: string
  count: number
  why: string
  children: ReactNode[]
}) {
  const [all, setAll] = useState(false)
  const rows = all ? children : children.slice(0, FIRST_ROWS)
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 border-b px-4 py-3">
        <Icon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 flex-1">
          <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">
            {title}
            <Badge variant="secondary">{count}</Badge>
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{why}</p>
        </div>
      </div>
      <ul className="divide-y">{rows}</ul>
      {children.length > FIRST_ROWS && (
        <div className="border-t px-2 py-1.5">
          <Button variant="ghost" size="sm" onClick={() => setAll((v) => !v)} aria-expanded={all}>
            {all ? 'Show fewer' : `Show all ${children.length}`}
          </Button>
        </div>
      )}
    </Card>
  )
}

/** One finding row: what (monospace) on the left, a short fact on the right. */
export function FindingRow({ name, sub, aside }: { name: ReactNode; sub?: ReactNode; aside?: ReactNode }) {
  return (
    <li className="flex items-start gap-3 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-sm">{name}</p>
        {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
      </div>
      {aside && <div className="shrink-0 text-right text-xs text-muted-foreground tabular-nums">{aside}</div>}
    </li>
  )
}

/** "zipzy_hrm.attendance" with the schema dimmed. */
export function QualifiedName({ schema, name }: { schema: string; name: string }) {
  return (
    <span title={`${schema}.${name}`}>
      <span className="text-muted-foreground">{schema}.</span>
      {name}
    </span>
  )
}

/** "(status, created_at)" */
export function ColumnList({ columns }: { columns: string[] }) {
  return <span className="font-mono">({columns.join(', ') || 'expression'})</span>
}
