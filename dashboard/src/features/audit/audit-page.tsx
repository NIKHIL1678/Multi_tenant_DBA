import { History, SearchX, ShieldAlert } from 'lucide-react'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuditLog } from '@/features/audit/api'
import { AuditEntryRow } from '@/features/audit/audit-entry'
import { AUDIT_AREAS, describeEntry, type DescribeContext } from '@/features/audit/describe'
import { useMembers, useRoles } from '@/features/members/api'
import { dayKey, formatDay, humanize } from '@/lib/format'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { AuditEntry } from '@/lib/types'
import { useNow } from '@/lib/use-now'

const FILTERS = ['area', 'actor', 'period'] as const
type FilterKey = (typeof FILTERS)[number]

export function AuditPage() {
  const { tenant, can } = useTenant()
  if (!can(Permission.AuditRead)) {
    return (
      <>
        <PageHeader title="Audit log" />
        <EmptyState
          icon={ShieldAlert}
          title="You do not have access to the audit log"
          description="Owners, DBAs and IT Admins can see it. Ask an Owner of this company if you need it."
        />
      </>
    )
  }
  return <AuditLog tenantId={tenant.id} />
}

function AuditLog({ tenantId }: { tenantId: string }) {
  const now = useNow()
  const [params, setParams] = useSearchParams()
  const filter = (key: FilterKey) => params.get(key) ?? ''
  const setFilter = (key: FilterKey, value: string) =>
    setParams(
      (p) => {
        if (value) p.set(key, value)
        else p.delete(key)
        return p
      },
      { replace: true },
    )
  const clearFilters = () =>
    setParams(
      (p) => {
        for (const k of FILTERS) p.delete(k)
        return p
      },
      { replace: true },
    )
  const filtering = FILTERS.some((k) => params.get(k))

  const log = useAuditLog(tenantId, {
    area: filter('area') || undefined,
    actorId: filter('actor') || undefined,
    period: filter('period') || undefined,
  })
  const members = useMembers(tenantId)
  const roles = useRoles(tenantId)

  // Names for sentences: role keys and member ids -> what people recognise.
  const roleNames = useMemo(() => new Map((roles.data ?? []).map((r) => [r.key, r.name])), [roles.data])
  const memberNames = useMemo(
    () => new Map((members.data ?? []).map((m) => [m.id, m.full_name ?? m.email])),
    [members.data],
  )
  const roleName = useCallback(
    (key: unknown) => (typeof key === 'string' ? (roleNames.get(key) ?? humanize(key)) : '?'),
    [roleNames],
  )
  const memberName = useCallback(
    (id: string | null) => (id ? (memberNames.get(id) ?? 'a former member') : 'a member'),
    [memberNames],
  )
  const ctx: DescribeContext = useMemo(() => ({ roleName, memberName }), [roleName, memberName])

  // Newest first, grouped under a heading per day.
  const entries = useMemo(() => log.data?.pages.flatMap((p) => p.items) ?? [], [log.data])
  const days = useMemo(() => {
    const groups: { key: string; first: string; items: AuditEntry[] }[] = []
    for (const e of entries) {
      const key = dayKey(e.created_at)
      const last = groups.at(-1)
      if (last && last.key === key) last.items.push(e)
      else groups.push({ key, first: e.created_at, items: [e] })
    }
    return groups
  }, [entries])

  return (
    <>
      <PageHeader title="Audit log" description="Every change in this company: who did it, what changed, and when. Kept permanently." />

      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        <NativeSelect value={filter('area')} onChange={(e) => setFilter('area', e.target.value)} aria-label="Filter by area">
          <option value="">Everything</option>
          {AUDIT_AREAS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={filter('actor')} onChange={(e) => setFilter('actor', e.target.value)} aria-label="Filter by person">
          <option value="">Anyone</option>
          {(members.data ?? [])
            .slice()
            .sort((a, b) => (a.full_name ?? a.email).localeCompare(b.full_name ?? b.email))
            .map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name ?? m.email}
              </option>
            ))}
        </NativeSelect>
        <NativeSelect value={filter('period')} onChange={(e) => setFilter('period', e.target.value)} aria-label="Filter by time">
          <option value="">All time</option>
          <option value="1d">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </NativeSelect>
      </div>

      {log.isError ? (
        <QueryError error={log.error} />
      ) : log.isLoading ? (
        <TimelineSkeleton />
      ) : entries.length === 0 ? (
        filtering ? (
          <EmptyState
            icon={SearchX}
            title="Nothing matches these filters"
            action={
              <Button variant="outline" onClick={clearFilters}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState icon={History} title="No activity yet" description="Changes made in this company appear here." />
        )
      ) : (
        <div className="grid gap-6">
          {days.map((day) => (
            <section key={day.key} aria-labelledby={`day-${day.key}`}>
              <h2 id={`day-${day.key}`} className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {formatDay(day.first, now)}
              </h2>
              <Card className="overflow-hidden">
                <ul className="divide-y">
                  {day.items.map((e) => (
                    <AuditEntryRow key={e.id} entry={e} sentence={describeEntry(e, ctx)} />
                  ))}
                </ul>
              </Card>
            </section>
          ))}

          <div className="flex flex-col items-center gap-2 pb-4">
            {log.hasNextPage ? (
              <Button variant="outline" onClick={() => void log.fetchNextPage()} busy={log.isFetchingNextPage}>
                Load older entries
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">That’s everything{filtering ? ' for these filters' : ''}.</p>
            )}
            <p className="text-xs text-muted-foreground">
              {entries.length} entr{entries.length === 1 ? 'y' : 'ies'} shown
            </p>
          </div>
        </div>
      )}
    </>
  )
}

function TimelineSkeleton() {
  return (
    <div className="grid gap-2" aria-busy aria-label="Loading audit log">
      <Skeleton className="h-3 w-16" />
      <Card className="divide-y">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center gap-3 px-5 py-3">
            <Skeleton className="size-8 rounded-full" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </Card>
    </div>
  )
}