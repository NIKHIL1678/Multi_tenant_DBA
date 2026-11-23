import { ArrowLeft, Database, RefreshCw, SearchX, Unplug } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { EmptyState } from '@/components/empty-state'
import { QueryError } from '@/components/query-error'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { TabCount, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCollect, useDatasource, useSnapshots } from '@/features/datasources/api'
import { DatasourceStatusBadge, EngineBadge, EnvironmentTag } from '@/features/datasources/datasource-badges'
import { ServerDatabaseList } from '@/features/datasources/server-databases-sheet'
import { attentionItems, type ServerTab } from '@/features/datasources/server/attention'
import { IndexesTab } from '@/features/datasources/server/indexes-tab'
import { OverviewTab } from '@/features/datasources/server/overview-tab'
import { QueriesTab } from '@/features/datasources/server/queries-tab'
import { TablesTab } from '@/features/datasources/server/tables-tab'
import { describeError, isNotFound } from '@/lib/api'
import { formatDateTime, formatRelative } from '@/lib/format'
import { useTenant } from '@/lib/tenant-context'
import type { Datasource, ServerSnapshots } from '@/lib/types'
import { useNow } from '@/lib/use-now'

const TABS: ServerTab[] = ['overview', 'databases', 'tables', 'indexes', 'queries']
const SUPPORTED = new Set(['postgres', 'mysql', 'mariadb'])
const STALE_AFTER_MS = 15 * 60_000 // opening the page refreshes statistics older than this

/** Newest and oldest collection time across the collectors every connector version has. */
function collectedTimes(s: ServerSnapshots | undefined): { newest?: string; oldest?: string; missing: boolean } {
  const times = [s?.health, s?.table_stats, s?.indexes].map((x) => x?.collected_at)
  const known = times.filter((t): t is string => !!t).sort()
  return { newest: known.at(-1), oldest: known[0], missing: known.length < times.length }
}

export function ServerPage() {
  const { tenant } = useTenant()
  const { datasourceId = '' } = useParams()
  const ds = useDatasource(tenant.id, datasourceId)

  if (ds.isError)
    return isNotFound(ds.error) ? (
      <EmptyState
        icon={SearchX}
        title="Database not found"
        description="It may have been removed, or it is in an environment you cannot see."
        action={
          <Button asChild variant="outline">
            <Link to=".." relative="path">
              Back to databases
            </Link>
          </Button>
        }
      />
    ) : (
      <QueryError error={ds.error} />
    )
  if (!ds.data) return <PageSkeleton />
  return <Server key={ds.data.id} tenantId={tenant.id} datasource={ds.data} />
}

function Server({ tenantId, datasource: d }: { tenantId: string; datasource: Datasource }) {
  const now = useNow()
  const snapshots = useSnapshots(tenantId, d.id)
  const collect = useCollect(tenantId, d.id)
  const [params, setParams] = useSearchParams()
  const tab = (TABS.includes(params.get('tab') as ServerTab) ? params.get('tab') : 'overview') as ServerTab
  const setTab = (t: ServerTab) =>
    setParams(
      (p) => {
        if (t === 'overview') p.delete('tab')
        else p.set('tab', t)
        return p
      },
      { replace: true },
    )

  const online = d.connector.status === 'online'
  const supported = SUPPORTED.has(d.engine)
  const data = collect.data ?? snapshots.data
  const { newest, oldest, missing } = collectedTimes(data)

  // Opening the page refreshes statistics that are missing or old (once per visit).
  const autoRan = useRef(false)
  useEffect(() => {
    if (autoRan.current || !snapshots.data || !online || !supported) return
    const { oldest: first, missing: gaps } = collectedTimes(snapshots.data)
    if (gaps || !first || Date.now() - new Date(first).getTime() > STALE_AFTER_MS) {
      autoRan.current = true
      collect.mutate(undefined)
    }
  }, [snapshots.data, online, supported, collect])

  const errors = collect.data?.errors ?? []
  const attention = attentionItems(data)
  const problems = attention.filter((i) => i.tab === 'indexes').length
  const queryProblems = attention.filter((i) => i.tab === 'queries' && i.level === 'warning').length
  const outdated = errors.find(
    (e) => (e.collector === 'slow_queries' || e.collector === 'locks') && e.code === 'outdated_connector',
  )

  const notCollected = (what: string) =>
    collect.isPending ? (
      <div className="grid gap-3" aria-busy aria-label={`Collecting ${what}`}>
        <Skeleton className="h-24" />
        <Skeleton className="h-48" />
      </div>
    ) : (
      <EmptyState
        icon={Database}
        title={`No ${what} yet`}
        description={
          !supported
            ? `Not available for this engine yet.`
            : online
              ? 'Collect to read them from the server. Only statistics are read, never your rows.'
              : `Connector ${d.connector.name} is offline. Statistics are collected once it is back.`
        }
        action={
          supported &&
          online && (
            <Button onClick={() => collect.mutate(undefined)}>
              <RefreshCw />
              Collect now
            </Button>
          )
        }
      />
    )

  return (
    <>
      <Link
        to=".."
        relative="path"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Databases
      </Link>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="grid min-w-0 gap-2">
          <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">{d.local_name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <EngineBadge engine={d.engine} version={d.version} />
            <EnvironmentTag name={d.environment.name} production={d.environment.is_production} />
            <DatasourceStatusBadge status={d.status} />
            <span className="text-sm text-muted-foreground">via {d.connector.name}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-start gap-1 sm:items-end">
          <Button
            variant="outline"
            onClick={() => collect.mutate(undefined)}
            disabled={collect.isPending || !online || !supported}
            title={!online ? `Connector ${d.connector.name} is offline` : undefined}
          >
            <RefreshCw className={collect.isPending ? 'animate-spin' : undefined} />
            {collect.isPending ? 'Collecting…' : 'Collect now'}
          </Button>
          <p className="text-xs text-muted-foreground" title={newest ? formatDateTime(newest) : undefined}>
            {newest
              ? `Collected ${formatRelative(missing || !oldest ? newest : oldest, now)}`
              : online
                ? 'Not collected yet'
                : 'Connector offline'}
          </p>
        </div>
      </div>

      {collect.isError && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not collect</AlertTitle>
          <AlertDescription>{describeError(collect.error)}</AlertDescription>
        </Alert>
      )}
      {errors.length > 0 && (
        <Alert variant="warning" className="mb-4">
          <AlertTitle>Some statistics could not be collected</AlertTitle>
          {errors.map((e) => (
            <AlertDescription key={e.collector}>
              <span className="font-medium">{COLLECTOR_LABELS[e.collector]}:</span> {e.message}
            </AlertDescription>
          ))}
        </Alert>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as ServerTab)}>
        <TabsList aria-label="Server details">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="databases">
            Databases <TabCount>{d.catalog?.database_count}</TabCount>
          </TabsTrigger>
          <TabsTrigger value="tables">
            Tables <TabCount>{data?.table_stats?.data.total_tables}</TabCount>
          </TabsTrigger>
          <TabsTrigger value="indexes">
            Indexes <TabCount>{data?.indexes ? problems || undefined : undefined}</TabCount>
          </TabsTrigger>
          <TabsTrigger value="queries">
            Queries <TabCount>{queryProblems || undefined}</TabCount>
          </TabsTrigger>
        </TabsList>

        {snapshots.isError ? (
          <QueryError error={snapshots.error} />
        ) : !data ? (
          <PageSkeleton tabsOnly />
        ) : (
          <>
            <TabsContent value="overview">
              {data.health || data.table_stats || data.indexes ? (
                <OverviewTab datasource={d} snapshots={data} onTab={setTab} />
              ) : (
                notCollected('statistics')
              )}
            </TabsContent>
            <TabsContent value="databases" className="grid gap-3">
              <ServerDatabaseList tenantId={tenantId} datasource={d} />
            </TabsContent>
            <TabsContent value="tables">
              {data.table_stats ? <TablesTab data={data.table_stats.data} /> : notCollected('table statistics')}
            </TabsContent>
            <TabsContent value="indexes">
              {data.indexes ? <IndexesTab data={data.indexes.data} /> : notCollected('index statistics')}
            </TabsContent>
            <TabsContent value="queries">
              {data.slow_queries || data.locks ? (
                <QueriesTab slow={data.slow_queries?.data} locks={data.locks?.data} />
              ) : outdated ? (
                <EmptyState
                  icon={Unplug}
                  title="Update the connector to see queries and locks"
                  description={`${outdated.message} Download it again from Connectors, or pull the new Docker image, and restart it.`}
                />
              ) : (
                notCollected('query statistics')
              )}
            </TabsContent>
          </>
        )}
      </Tabs>
    </>
  )
}

const COLLECTOR_LABELS: Record<string, string> = {
  health: 'Health',
  table_stats: 'Tables',
  indexes: 'Indexes',
  slow_queries: 'Slow queries',
  locks: 'Locks',
  table_index: 'Table list',
}

function PageSkeleton({ tabsOnly = false }: { tabsOnly?: boolean }) {
  return (
    <div className="grid gap-4" aria-busy aria-label="Loading">
      {!tabsOnly && (
        <>
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-6 w-80" />
        </>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-48" />
    </div>
  )
}
