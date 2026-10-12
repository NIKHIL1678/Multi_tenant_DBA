import { Database, Info, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'

import { CodeBlock } from '@/components/code-block'
import { QueryError } from '@/components/query-error'
import { SearchInput } from '@/components/search-input'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useServerDatabases } from '@/features/datasources/api'
import { EngineBadge, EnvironmentTag } from '@/features/datasources/datasource-badges'
import { formatBytes, formatDateTime, formatRelative } from '@/lib/format'
import type { CatalogDatabase, Datasource } from '@/lib/types'
import { useNow } from '@/lib/use-now'

/** What a MySQL / MariaDB monitoring user needs to list databases. Never gives row access. */
const MYSQL_GRANT = `GRANT SHOW DATABASES, SHOW VIEW
  ON *.* TO 'zipzy_monitor'@'%';`

const SEARCH_FROM = 8 // show a search box once the list is longer than this

/** MySQL / MariaDB monitoring users need two extra grants to see databases and their sizes. */
function missingGrants(d: Datasource): {
  cannotList: boolean
  noSizes: boolean
} {
  const caps = d.capabilities ?? {}
  const isMysql = d.engine === 'mysql' || d.engine === 'mariadb'
  return {
    cannotList: isMysql && caps.list_databases === false,
    noSizes: isMysql && caps.table_metadata === false,
  }
}

/** "3 databases · 8.3 GB" for a table cell; a dash until the connector reports them. */
export function CatalogSummary({ datasource: d, onOpen }: { datasource: Datasource; onOpen: () => void }) {
  const c = d.catalog
  if (!c) return <span className="text-muted-foreground">—</span>
  const label = missingGrants(d).cannotList
    ? 'Needs a grant'
    : `${c.database_count}${c.truncated ? '+' : ''} ${c.database_count === 1 ? 'database' : 'databases'}`
  return (
    <button
      type="button"
      onClick={onOpen}
      className="text-left font-medium text-link underline-offset-4 outline-none hover:underline focus-visible:underline"
      aria-label={`Show the databases on ${d.local_name}`}
    >
      {label}
      {c.total_size_bytes !== null && (
        <span className="font-normal text-muted-foreground"> · {formatBytes(c.total_size_bytes)}</span>
      )}
    </button>
  )
}

/** Side panel listing every database on one server, biggest first. */
export function ServerDatabasesSheet({
  tenantId,
  datasource,
  open,
  onOpenChange,
  onCheck,
  checking,
}: {
  tenantId: string
  datasource: Datasource | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCheck: (d: Datasource) => void
  checking: boolean
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        title={datasource ? `Databases on ${datasource.local_name}` : 'Databases'}
        className="w-full max-w-full bg-background sm:max-w-md"
      >
        {datasource && (
          <Body
            key={datasource.id}
            tenantId={tenantId}
            datasource={datasource}
            onCheck={() => onCheck(datasource)}
            checking={checking}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}

function Body({
  tenantId,
  datasource: d,
  onCheck,
  checking,
}: {
  tenantId: string
  datasource: Datasource
  onCheck: () => void
  checking: boolean
}) {
  const now = useNow()
  const catalog = useServerDatabases(tenantId, d.id)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="grid gap-2 border-b p-4 pr-12">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Databases on this server</p>
        <h2 className="truncate font-mono text-lg font-semibold">{d.local_name}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <EngineBadge engine={d.engine} version={d.version} />
          <EnvironmentTag name={d.environment.name} production={d.environment.is_production} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span title={catalog.data?.updated_at ? formatDateTime(catalog.data.updated_at) : undefined}>
            {catalog.data?.updated_at ? `Updated ${formatRelative(catalog.data.updated_at, now)}` : 'Not reported yet'}
          </span>
          <Button variant="outline" size="sm" onClick={onCheck} disabled={checking}>
            <RefreshCw className={checking ? 'animate-spin' : undefined} />
            {checking ? 'Checking…' : 'Refresh now'}
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-4">
        <ServerDatabaseList tenantId={tenantId} datasource={d} />
      </div>
    </div>
  )
}

function DatabaseRow({ db }: { db: CatalogDatabase }) {
  return (
    <li className="flex items-center gap-3 p-3">
      <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-sm font-medium" title={db.name}>
          {db.name}
        </p>
        {db.tables !== null && (
          <p className="text-xs text-muted-foreground">
            {db.tables} {db.tables === 1 ? 'table' : 'tables'}
          </p>
        )}
      </div>
      <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
        {db.size_bytes !== null ? formatBytes(db.size_bytes) : '—'}
      </span>
    </li>
  )
}

/** Every database on one server, biggest first, with a hint when the monitoring user needs grants. */
export function ServerDatabaseList({ tenantId, datasource: d }: { tenantId: string; datasource: Datasource }) {
  const catalog = useServerDatabases(tenantId, d.id)
  const [search, setSearch] = useState('')

  const databases = useMemo(() => catalog.data?.databases ?? [], [catalog.data])
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? databases.filter((db) => db.name.toLowerCase().includes(q)) : databases
  }, [databases, search])

  const { cannotList, noSizes } = missingGrants(d)

  return (
    <>
      {(cannotList || noSizes) && (
        <div className="grid gap-2 rounded-lg border bg-muted/40 p-3 text-sm">
          <p className="flex items-start gap-2">
            <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span>
              {cannotList
                ? 'The monitoring user cannot see the databases on this server.'
                : 'The monitoring user cannot see table sizes.'}{' '}
              Run this on the server as an admin. It shows names and sizes only, never rows:
            </span>
          </p>
          <CodeBlock code={MYSQL_GRANT} label="Grant for the monitoring user" />
          <p className="text-xs text-muted-foreground">
            Use your monitoring user’s name. If it also exists as{' '}
            <code className="font-mono">'zipzy_monitor'@'localhost'</code>, run it for that one too. The list updates at
            the next check.
          </p>
        </div>
      )}

      {catalog.isError ? (
        <QueryError error={catalog.error} />
      ) : catalog.isLoading ? (
        <div className="grid gap-2" aria-busy aria-label="Loading databases">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : databases.length === 0 && cannotList ? null : databases.length === 0 ? (
        <div className="grid justify-items-center gap-2 py-10 text-center">
          <Database className="size-8 text-muted-foreground" aria-hidden />
          <p className="text-sm font-medium">
            {catalog.data?.updated_at ? 'No databases found' : 'No list of databases yet'}
          </p>
          <p className="max-w-xs text-sm text-muted-foreground">
            {catalog.data?.updated_at
              ? 'The server reported no databases besides its system ones.'
              : 'It appears after the next check. Connectors older than version 0.3.0 do not send it: update the connector.'}
          </p>
        </div>
      ) : (
        <>
          {databases.length > SEARCH_FROM && (
            <SearchInput
              value={search}
              onValueChange={setSearch}
              placeholder="Search databases"
              aria-label="Search databases on this server"
            />
          )}
          <ul className="divide-y rounded-lg border" aria-label={`Databases on ${d.local_name}`}>
            {shown.map((db) => (
              <DatabaseRow key={db.name} db={db} />
            ))}
            {shown.length === 0 && <li className="p-3 text-sm text-muted-foreground">No database matches.</li>}
          </ul>
          <p className="text-xs text-muted-foreground">
            {catalog.data?.truncated
              ? `Showing the ${databases.length} biggest; the server has more.`
              : `${databases.length} ${databases.length === 1 ? 'database' : 'databases'}, biggest first. System databases are left out.`}{' '}
            Sizes are the server’s own estimates.
            {d.engine === 'postgres' && ' Table counts are shown for the database the connector logs in to.'}
          </p>
        </>
      )}
    </>
  )
}
