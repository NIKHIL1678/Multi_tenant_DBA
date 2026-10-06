import { Badge } from '@/components/ui/badge'
import { DATASOURCE_STATUS, engineLabel } from '@/features/datasources/labels'

/** Engine name, e.g. "PostgreSQL 16.4". */
export function EngineBadge({ engine, version }: { engine: string; version?: string | null }) {
  return (
    <Badge variant="outline" className="font-normal">
      <span className="font-medium">{engineLabel(engine)}</span>
      {version && <span className="text-muted-foreground">{version}</span>}
    </Badge>
  )
}

export function DatasourceStatusBadge({ status }: { status: string }) {
  const s = DATASOURCE_STATUS[status] ?? DATASOURCE_STATUS.unknown
  return <Badge variant={s.variant}>{s.label}</Badge>
}

/** Environment name, marked when it is production. */
export function EnvironmentTag({ name, production }: { name: string; production: boolean }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <span className="truncate font-mono text-sm">{name}</span>
      {production && <Badge variant="warning">Prod</Badge>}
    </span>
  )
}
