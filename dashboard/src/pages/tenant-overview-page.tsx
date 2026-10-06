import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { ErrorAlert } from '@/components/ui/alert'
import { Card } from '@/components/ui/card'
import { FullPageSpinner } from '@/components/ui/spinner'
import { api, ApiError, describeError } from '@/lib/api'
import type { Tenant, TenantOverview } from '@/lib/types'

export function TenantOverviewPage() {
  const { tenantId = '' } = useParams()

  const tenant = useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => api<Tenant>(`/v1/tenants/${tenantId}`),
  })
  const overview = useQuery({
    queryKey: ['tenant', tenantId, 'overview'],
    queryFn: () => api<TenantOverview>(`/v1/tenants/${tenantId}/overview`),
    enabled: tenant.isSuccess,
  })

  if (tenant.isPending) return <FullPageSpinner />
  if (tenant.isError) {
    // 404: not a member / no such company. 422: the id in the URL is not even a valid id.
    if (tenant.error instanceof ApiError && [404, 422].includes(tenant.error.status)) {
      return (
        <div className="space-y-3">
          <h1 className="text-xl font-semibold">Company not found</h1>
          <p className="text-sm text-slate-600">It does not exist, or you are not a member.</p>
          <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
            Back to your companies
          </Link>
        </div>
      )
    }
    return <ErrorAlert>{describeError(tenant.error)}</ErrorAlert>
  }

  const t = tenant.data
  const o = overview.data
  const connectorTotal = o ? sum(o.connectors_by_status) : null
  const databaseTotal = o ? sum(o.datasources_by_engine) : null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-700">
            ← All companies
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{t.name}</h1>
          <p className="text-sm text-slate-500">
            {t.slug} · {t.plan} plan
          </p>
        </div>
        <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
          You are {t.my_role_key.replace('_', ' ')}
        </span>
      </div>

      {overview.isError && <ErrorAlert>{describeError(overview.error)}</ErrorAlert>}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Environments" value={o?.environments} />
        <Stat label="Members" value={o?.members} />
        <Stat label="Connectors" value={connectorTotal} detail={o && breakdown(o.connectors_by_status)} />
        <Stat label="Databases" value={databaseTotal} detail={o && breakdown(o.datasources_by_engine)} />
      </div>

      {o && connectorTotal === 0 && (
        <Card className="border-dashed">
          <h2 className="font-medium">Connect your first database</h2>
          <p className="mt-1 text-sm text-slate-600">
            Install a connector inside your network. It keeps your database passwords on your side and
            only sends us health and performance information.
          </p>
        </Card>
      )}
    </div>
  )
}

function Stat({ label, value, detail }: { label: string; value: number | null | undefined; detail?: string | null }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value ?? '—'}</p>
      {detail && <p className="mt-1 truncate text-xs text-slate-500">{detail}</p>}
    </Card>
  )
}

function sum(counts: Record<string, number>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0)
}

function breakdown(counts: Record<string, number>): string | null {
  const parts = Object.entries(counts).map(([k, n]) => `${n} ${k}`)
  return parts.length ? parts.join(' · ') : null
}