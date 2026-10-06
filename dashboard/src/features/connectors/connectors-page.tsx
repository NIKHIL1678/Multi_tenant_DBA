import { Plus, PlugZap, SearchX } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
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
import { AddConnectorDialog } from '@/features/connectors/add-connector-dialog'
import { useConnectors, useRevokeConnector } from '@/features/connectors/api'
import { ConnectorActions, type ConnectorActionKind } from '@/features/connectors/connector-actions'
import { ConnectorStatusBadge } from '@/features/connectors/connector-status'
import { NewCommandDialog } from '@/features/connectors/new-command-dialog'
import { RenameConnectorDialog } from '@/features/connectors/rename-connector-dialog'
import { formatDate, formatDateTime, formatRelative } from '@/lib/format'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { Connector } from '@/lib/types'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

type StatusFilter = 'all' | 'online' | 'offline' | 'pending' | 'revoked'

/** Open dialog. `open` turns false first so the closing animation still has its content. */
type Action = { kind: ConnectorActionKind; connector: Connector; open: boolean }

export function ConnectorsPage() {
  const { tenant, can } = useTenant()
  const canManage = can(Permission.ConnectorsManage)
  const connectors = useConnectors(tenant.id)
  const revoke = useRevokeConnector(tenant.id)
  const now = useNow()

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [addOpen, setAddOpen] = useState(false)
  const [action, setAction] = useState<Action | null>(null)

  const all = useMemo(() => connectors.data ?? [], [connectors.data])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return all.filter((c) => (!q || c.name.toLowerCase().includes(q)) && (status === 'all' || c.status === status))
  }, [all, search, status])
  const online = all.filter((c) => c.status === 'online').length
  const active = all.filter((c) => c.status !== 'revoked').length

  const openAction = (kind: ConnectorActionKind, connector: Connector) => {
    revoke.reset()
    setAction({ kind, connector, open: true })
  }
  const close = (o: boolean) => {
    if (!o) setAction((a) => a && { ...a, open: false })
  }
  const isOpen = (kind: ConnectorActionKind) => action?.kind === kind && action.open
  const target = action?.connector ?? null

  async function confirmRevoke() {
    if (!target) return
    const ok = await revoke.mutateAsync(target.id).then(
      () => true,
      () => false,
    )
    if (!ok) return
    toast.success(`${target.name} is revoked`)
    close(false)
  }

  const actionsFor = (c: Connector) => (canManage ? <ConnectorActions connector={c} onAction={openAction} /> : null)

  return (
    <>
      <PageHeader
        title="Connectors"
        description={
          connectors.data
            ? `${active} active, ${online} online. Connectors run inside your network; database passwords never leave it.`
            : 'Programs inside your network that reach your databases.'
        }
        actions={
          canManage && (
            <Button onClick={() => setAddOpen(true)}>
              <Plus />
              Add connector
            </Button>
          )
        }
      />

      {connectors.isError ? (
        <QueryError error={connectors.error} />
      ) : connectors.isLoading ? (
        <ListSkeleton />
      ) : all.length === 0 ? (
        <EmptyState
          icon={PlugZap}
          title="No connectors yet"
          description="Install a connector on a server inside your network. It reaches your databases, so we never need their passwords."
          action={canManage && <Button onClick={() => setAddOpen(true)}>Add connector</Button>}
        />
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_13rem]">
            <SearchInput value={search} onValueChange={setSearch} placeholder="Search connectors" aria-label="Search connectors" />
            <NativeSelect value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="online">Online</option>
              <option value="offline">Offline</option>
              <option value="pending">Waiting for install</option>
              <option value="revoked">Revoked</option>
            </NativeSelect>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No connectors match"
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setSearch('')
                    setStatus('all')
                  }}
                >
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
                      <TableHead>Connector</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last seen</TableHead>
                      <TableHead className="text-right">Databases</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead className="w-14">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((c) => (
                      <TableRow key={c.id} className={cn(c.status === 'revoked' && 'text-muted-foreground')}>
                        <TableCell className="max-w-72">
                          <p className="truncate font-medium">{c.name}</p>
                          {c.version && <p className="text-xs text-muted-foreground">v{c.version}</p>}
                        </TableCell>
                        <TableCell>
                          <ConnectorStatusBadge status={c.status} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-sm">
                          <LastSeen connector={c} now={now} />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          <DatabaseCount count={c.datasource_count} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(c.created_at)}>
                          {formatDate(c.created_at)}
                        </TableCell>
                        <TableCell className="text-right">{actionsFor(c)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Phones: cards */}
              <ul className="divide-y md:hidden">
                {filtered.map((c) => (
                  <li key={c.id} className={cn('grid gap-2 p-4', c.status === 'revoked' && 'text-muted-foreground')}>
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1 pt-1">
                        <p className="truncate font-medium">{c.name}</p>
                        {c.version && <p className="text-xs text-muted-foreground">v{c.version}</p>}
                      </div>
                      <div className="-mr-2">{actionsFor(c)}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                      <ConnectorStatusBadge status={c.status} />
                      <DatabaseCount count={c.datasource_count} withLabel />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      <LastSeen connector={c} now={now} />
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {canManage && (
        <>
          <AddConnectorDialog open={addOpen} onOpenChange={setAddOpen} tenantId={tenant.id} />
          <RenameConnectorDialog open={isOpen('rename')} onOpenChange={close} tenantId={tenant.id} connector={target} />
          <NewCommandDialog open={isOpen('command')} onOpenChange={close} tenantId={tenant.id} connector={target} />
          <ConfirmDialog
            open={isOpen('revoke')}
            onOpenChange={close}
            title={`Revoke ${target?.name ?? ''}?`}
            description={
              target && target.datasource_count > 0
                ? `It stops working straight away and can never reconnect. Its ${target.datasource_count} database${target.datasource_count === 1 ? '' : 's'} become unreachable until moved to another connector.`
                : 'It stops working straight away and can never reconnect. To use that server again, add a new connector.'
            }
            confirmLabel="Revoke connector"
            destructive
            requireText={target?.name}
            busy={revoke.isPending}
            error={revoke.error}
            onConfirm={() => void confirmRevoke()}
          />
        </>
      )}
    </>
  )
}

/** What "last seen" means depends on the status. */
function LastSeen({ connector: c, now }: { connector: Connector; now: number }) {
  if (c.status === 'revoked' && c.revoked_at) {
    return <span title={formatDateTime(c.revoked_at)}>Revoked {formatRelative(c.revoked_at, now)}</span>
  }
  if (c.status === 'pending') {
    if (!c.enrollment_expires_at || new Date(c.enrollment_expires_at).getTime() < now) {
      return <span className="text-warning">Install command expired</span>
    }
    return (
      <span className="text-muted-foreground" title={formatDateTime(c.enrollment_expires_at)}>
        Command expires {formatRelative(c.enrollment_expires_at, now)}
      </span>
    )
  }
  if (!c.last_seen_at) return <span className="text-muted-foreground">Not seen yet</span>
  return (
    <span className="text-muted-foreground" title={formatDateTime(c.last_seen_at)}>
      Seen {formatRelative(c.last_seen_at, now)}
    </span>
  )
}

function DatabaseCount({ count, withLabel = false }: { count: number; withLabel?: boolean }) {
  const text = withLabel ? `${count} database${count === 1 ? '' : 's'}` : String(count)
  if (count === 0) return <span className="text-muted-foreground">{text}</span>
  return (
    <Link to="../databases" className="font-medium text-primary underline-offset-4 hover:underline">
      {text}
    </Link>
  )
}

function ListSkeleton() {
  return (
    <div className="grid gap-4" aria-busy aria-label="Loading connectors">
      <Skeleton className="h-9 w-full" />
      <Card className="divide-y">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-4 p-4">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-5 w-24" />
            <Skeleton className="ml-auto h-4 w-16" />
          </div>
        ))}
      </Card>
    </div>
  )
}