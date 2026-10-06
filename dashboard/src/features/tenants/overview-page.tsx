import { Database, Layers, PlugZap, Users, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'

import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useTenantOverview } from '@/features/tenants/api'
import { humanize } from '@/lib/format'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'

export function OverviewPage() {
  const { tenant, can } = useTenant()
  const overview = useTenantOverview(tenant.id)
  const o = overview.data

  const connectors = o ? sum(o.connectors_by_status) : undefined
  const databases = o ? sum(o.datasources_by_engine) : undefined

  return (
    <>
      <PageHeader
        title={tenant.name}
        description={`${tenant.slug} · ${humanize(tenant.plan)} plan`}
        actions={<Badge>You are {humanize(tenant.my_role_key)}</Badge>}
      />

      {overview.isError && <QueryError error={overview.error} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat icon={Layers} label="Environments" value={o?.environments} to="environments" />
        <Stat icon={Users} label="Members" value={o?.members} to="members" />
        <Stat icon={PlugZap} label="Connectors" value={connectors} detail={o && breakdown(o.connectors_by_status)} to="connectors" />
        <Stat icon={Database} label="Databases" value={databases} detail={o && breakdown(o.datasources_by_engine)} to="databases" />
      </div>

      {o && connectors === 0 && (
        <Card className="mt-6 flex flex-col gap-4 border-dashed p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div>
            <h2 className="font-medium">Connect your first database</h2>
            <p className="mt-1 max-w-xl text-sm text-muted-foreground">
              Install a connector inside your network. Your database passwords stay on your side; we only receive
              health and performance information.
            </p>
          </div>
          {can(Permission.ConnectorsManage) && (
            <Button asChild className="shrink-0">
              <Link to="connectors">Add a connector</Link>
            </Button>
          )}
        </Card>
      )}
    </>
  )
}

function Stat({
  icon: Icon,
  label,
  value,
  detail,
  to,
}: {
  icon: LucideIcon
  label: string
  value: number | undefined
  detail?: string | null
  to: string
}) {
  return (
    <Link
      to={to}
      className="rounded-xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none sm:p-5"
    >
      <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
        <span className="truncate">{label}</span>
        <Icon className="size-4 shrink-0" aria-hidden />
      </div>
      {value === undefined ? (
        <Skeleton className="mt-2 h-8 w-12" />
      ) : (
        <p className="mt-1 text-2xl font-semibold tabular-nums sm:text-3xl">{value}</p>
      )}
      <p className="mt-1 truncate text-xs text-muted-foreground">{detail || '\u00a0'}</p>
    </Link>
  )
}

function sum(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0)
}

function breakdown(counts: Record<string, number>): string | null {
  const parts = Object.entries(counts).map(([k, n]) => `${n} ${k}`)
  return parts.length ? parts.join(' · ') : null
}