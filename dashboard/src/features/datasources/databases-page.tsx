import { CircleHelp, Database, SearchX } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { SearchInput } from '@/components/search-input'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useConnectors } from '@/features/connectors/api'
import { AddDatabaseHelp } from '@/features/datasources/add-database-help'
import { useCheckDatasource, useDatasources, useDeleteDatasource } from '@/features/datasources/api'
import { DatasourceActions, type DatasourceActionKind } from '@/features/datasources/datasource-actions'
import { DatasourceStatusBadge, EngineBadge, EnvironmentTag } from '@/features/datasources/datasource-badges'
import { DATASOURCE_STATUS, ENGINE_LABELS } from '@/features/datasources/labels'
import { MoveDialog } from '@/features/datasources/move-dialog'
import { CatalogSummary, ServerDatabasesSheet } from '@/features/datasources/server-databases-sheet'
import { useEnvironments } from '@/features/environments/api'
import { describeError } from '@/lib/api'
import { formatDateTime, formatRelative } from '@/lib/format'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { Datasource } from '@/lib/types'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

/** Filters live in the URL, so links like ?environment=<id> from other pages land filtered. */
const FILTERS = ['environment', 'connector', 'engine', 'status'] as const
type FilterKey = (typeof FILTERS)[number]

/** Open dialog. `open` turns false first so the closing animation still has its content. */
type Action = { kind: DatasourceActionKind; datasource: Datasource; open: boolean }

export function DatabasesPage() {
  const { tenant, can } = useTenant()
  const canManage = can(Permission.DatasourcesManage)
  const isOwner = can(Permission.OrgManage)
  const now = useNow()

  const datasources = useDatasources(tenant.id)
  const environments = useEnvironments(tenant.id)
  const connectors = useConnectors(tenant.id)
  const remove = useDeleteDatasource(tenant.id)
  const check = useCheckDatasource(tenant.id)

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
  const [search, setSearch] = useState('')

  const all = useMemo(() => datasources.data ?? [], [datasources.data])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const env = params.get('environment')
    const con = params.get('connector')
    const eng = params.get('engine')
    const st = params.get('status')
    return all.filter(
      (d) =>
        (!q || d.local_name.toLowerCase().includes(q)) &&
        (!env || d.environment.id === env) &&
        (!con || d.connector.id === con) &&
        (!eng || d.engine === eng) &&
        (!st || d.status === st),
    )
  }, [all, search, params])

  const counts = useMemo(() => {
    const c: Record<string, number> = { connected: 0, error: 0, unknown: 0 }
    for (const d of all) c[d.status] = (c[d.status] ?? 0) + 1
    return c
  }, [all])

  const filtering = search !== '' || FILTERS.some((k) => params.get(k))
  const clearFilters = () => {
    setSearch('')
    setParams(
      (p) => {
        for (const k of FILTERS) p.delete(k)
        return p
      },
      { replace: true },
    )
  }

  const [helpOpen, setHelpOpen] = useState(false)
  const [action, setAction] = useState<Action | null>(null)
  const runCheck = (d: Datasource) => {
    check.mutate(d.id, {
      onSuccess: (ds) => {
        if (ds.status === 'connected') toast.success(`${ds.local_name} is reachable`)
        else toast.error(`${ds.local_name} could not be reached`)
      },
      onError: (err) => toast.error(describeError(err)),
    })
  }
  const openAction = (kind: DatasourceActionKind, datasource: Datasource) => {
    if (kind === 'check') {
      runCheck(datasource)
      return
    }
    remove.reset()
    setAction({ kind, datasource, open: true })
  }
  const close = (o: boolean) => {
    if (!o) setAction((a) => a && { ...a, open: false })
  }
  const isOpen = (kind: DatasourceActionKind) => action?.kind === kind && action.open
  const target = action?.datasource ?? null
  // The panel follows the live row, so a check refreshes what it shows.
  const live = (target && all.find((d) => d.id === target.id)) ?? target

  async function confirmRemove() {
    if (!target) return
    const ok = await remove.mutateAsync(target.id).then(
      () => true,
      () => false,
    )
    if (!ok) return
    toast.success(`${target.local_name} removed`)
    close(false)
  }

  const actionsFor = (d: Datasource) => (
    <DatasourceActions datasource={d} canManage={canManage} isOwner={isOwner} onAction={openAction} />
  )
  const showDatabases = (d: Datasource) => openAction('databases', d)

  return (
    <>
      <PageHeader
        title="Databases"
        description="Reported by your connectors. Passwords stay on your servers."
        actions={
          <Button variant="outline" onClick={() => setHelpOpen(true)}>
            <CircleHelp />
            Add a database
          </Button>
        }
      />

      {datasources.isError ? (
        <QueryError error={datasources.error} />
      ) : datasources.isLoading ? (
        <ListSkeleton />
      ) : all.length === 0 ? (
        <EmptyState
          icon={Database}
          title="No databases yet"
          description="Once a connector is running, the databases listed in its settings file appear here by themselves."
          action={<Button onClick={() => setHelpOpen(true)}>How to add a database</Button>}
        />
      ) : (
        <div className="grid gap-4">
          {/* Status summary: each tile is also a filter. */}
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {(['connected', 'error', 'unknown'] as const).map((s) => {
              const active = filter('status') === s
              return (
                <button
                  key={s}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setFilter('status', active ? '' : s)}
                  className={cn(
                    'rounded-xl border bg-card p-3 text-left shadow-xs transition-colors outline-none sm:p-4',
                    'hover:bg-accent/40 focus-visible:ring-[3px] focus-visible:ring-ring/50',
                    active && 'border-primary bg-accent/50',
                  )}
                >
                  <span className="block text-2xl font-semibold tabular-nums">{counts[s] ?? 0}</span>
                  <span className="block truncate text-xs text-muted-foreground sm:text-sm">{DATASOURCE_STATUS[s].label}</span>
                </button>
              )
            })}
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_11rem_11rem_11rem]">
            <SearchInput
              value={search}
              onValueChange={setSearch}
              placeholder="Search databases"
              aria-label="Search databases"
              className="sm:col-span-2 lg:col-span-1"
            />
            <NativeSelect value={filter('environment')} onChange={(e) => setFilter('environment', e.target.value)} aria-label="Filter by environment">
              <option value="">All environments</option>
              {(environments.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect value={filter('engine')} onChange={(e) => setFilter('engine', e.target.value)} aria-label="Filter by engine">
              <option value="">All engines</option>
              {Object.entries(ENGINE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect value={filter('connector')} onChange={(e) => setFilter('connector', e.target.value)} aria-label="Filter by connector">
              <option value="">All connectors</option>
              {(connectors.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No databases match"
              action={
                <Button variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <Card className="overflow-hidden">
              {/* Wide screens: table */}
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Server</TableHead>
                      <TableHead>Databases inside</TableHead>
                      <TableHead>Environment</TableHead>
                      <TableHead className="hidden lg:table-cell">Connector</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-14">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="max-w-72">
                          <ServerLink datasource={d} />
                          <EngineBadge engine={d.engine} version={d.version} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-sm">
                          <CatalogSummary datasource={d} onOpen={() => showDatabases(d)} />
                        </TableCell>
                        <TableCell className="max-w-48">
                          <EnvironmentTag name={d.environment.name} production={d.environment.is_production} />
                        </TableCell>
                        <TableCell className="hidden max-w-48 truncate text-muted-foreground lg:table-cell">{d.connector.name}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          <DatasourceStatusBadge status={d.status} />
                          <p className="mt-1 text-xs text-muted-foreground">
                            <Checked iso={d.last_checked_at} now={now} />
                          </p>
                        </TableCell>
                        <TableCell className="text-right">{actionsFor(d)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Phones: cards */}
              <ul className="divide-y md:hidden">
                {filtered.map((d) => (
                  <li key={d.id} className="grid gap-2 p-4">
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1 pt-1">
                        <ServerLink datasource={d} />
                      </div>
                      <div className="-mr-2">{actionsFor(d)}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <EngineBadge engine={d.engine} version={d.version} />
                      <DatasourceStatusBadge status={d.status} />
                    </div>
                    {d.catalog && (
                      <div className="text-sm">
                        <CatalogSummary datasource={d} onOpen={() => showDatabases(d)} />
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <EnvironmentTag name={d.environment.name} production={d.environment.is_production} />
                      <span className="truncate">via {d.connector.name}</span>
                      <Checked iso={d.last_checked_at} now={now} />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {filtering && filtered.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Showing {filtered.length} of {all.length} databases ·{' '}
              <button type="button" onClick={clearFilters} className="font-medium text-link underline-offset-4 hover:underline">
                Clear filters
              </button>
            </p>
          )}
        </div>
      )}

      <AddDatabaseHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <ServerDatabasesSheet
        tenantId={tenant.id}
        datasource={live}
        open={isOpen('databases')}
        onOpenChange={close}
        onCheck={runCheck}
        checking={check.isPending && check.variables === live?.id}
      />
      {canManage && (
        <>
          <MoveDialog
            open={isOpen('move')}
            onOpenChange={close}
            tenantId={tenant.id}
            datasource={target}
            environments={environments.data ?? []}
            isOwner={isOwner}
          />
          <ConfirmDialog
            open={isOpen('remove')}
            onOpenChange={close}
            title={`Remove ${target?.local_name ?? ''}?`}
            description="It disappears from ZipZy, along with its place in an environment. Nothing changes on the database itself. If it is still in the connector’s settings file, it will be reported again; remove it there to stop that."
            confirmLabel="Remove database"
            destructive
            busy={remove.isPending}
            error={remove.error}
            onConfirm={() => void confirmRemove()}
          />
        </>
      )}
    </>
  )
}

/** The server name opens its page (health, tables, indexes). */
function ServerLink({ datasource: d }: { datasource: Datasource }) {
  return (
    <Link
      to={d.id}
      className="block truncate font-mono font-medium underline-offset-4 outline-none hover:text-link hover:underline focus-visible:underline"
    >
      {d.local_name}
    </Link>
  )
}

function Checked({ iso, now }: { iso: string | null; now: number }) {
  if (!iso) return <span>Never checked</span>
  return <span title={formatDateTime(iso)}>Checked {formatRelative(iso, now)}</span>
}

function ListSkeleton() {
  return (
    <div className="grid gap-4" aria-busy aria-label="Loading databases">
      <div className="grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-9 w-full" />
      <Card className="divide-y">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-4 p-4">
            <div className="grid gap-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="ml-auto h-5 w-20" />
          </div>
        ))}
      </Card>
    </div>
  )
}
