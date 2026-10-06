import { Layers, Plus, SearchX } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { SearchInput } from '@/components/search-input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDeleteEnvironment, useEnvironments, useUpdateEnvironment } from '@/features/environments/api'
import { EnvironmentActions, type EnvironmentActionKind } from '@/features/environments/environment-actions'
import { EnvironmentFormDialog } from '@/features/environments/environment-form-dialog'
import { formatDate, formatDateTime } from '@/lib/format'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { Environment } from '@/lib/types'

type TypeFilter = 'all' | 'production' | 'other'

/** Open dialog. `open` turns false first so the closing animation still has its content. */
type Action = { kind: EnvironmentActionKind | 'create'; environment: Environment | null; open: boolean }

export function EnvironmentsPage() {
  const { tenant, can } = useTenant()
  const canManage = can(Permission.DatasourcesManage)
  const isOwner = can(Permission.OrgManage)

  const environments = useEnvironments(tenant.id)
  const update = useUpdateEnvironment(tenant.id)
  const remove = useDeleteEnvironment(tenant.id)

  const [search, setSearch] = useState('')
  const [type, setType] = useState<TypeFilter>('all')

  const all = useMemo(() => environments.data ?? [], [environments.data])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return all.filter(
      (e) =>
        (!q || e.name.includes(q)) &&
        (type === 'all' || (type === 'production') === e.is_production),
    )
  }, [all, search, type])
  const productionCount = all.filter((e) => e.is_production).length

  const [action, setAction] = useState<Action | null>(null)
  const open = (kind: Action['kind'], environment: Environment | null = null) => {
    update.reset()
    remove.reset()
    setAction({ kind, environment, open: true })
  }
  const close = (o: boolean) => {
    if (!o) setAction((a) => a && { ...a, open: false })
  }
  const isOpen = (...kinds: Action['kind'][]) => !!action?.open && kinds.includes(action.kind)
  const target = action?.environment ?? null

  async function setProduction(isProduction: boolean) {
    if (!target) return
    const ok = await update.mutateAsync({ id: target.id, is_production: isProduction }).then(
      () => true,
      () => false,
    )
    if (!ok) return
    toast.success(isProduction ? `${target.name} is now production` : `${target.name} is no longer production`)
    close(false)
  }

  async function deleteEnvironment() {
    if (!target) return
    const ok = await remove.mutateAsync(target.id).then(
      () => true,
      () => false,
    )
    if (!ok) return
    toast.success(`${target.name} deleted`)
    close(false)
  }

  const actionsFor = (env: Environment) =>
    canManage ? <EnvironmentActions environment={env} isOwner={isOwner} onAction={open} /> : null

  return (
    <>
      <PageHeader
        title="Environments"
        description={
          environments.data
            ? `${all.length} environment${all.length === 1 ? '' : 's'}, ${productionCount} production. Production gets the strictest protection.`
            : 'Separate production from staging and testing.'
        }
        actions={
          canManage && (
            <Button onClick={() => open('create')}>
              <Plus />
              New environment
            </Button>
          )
        }
      />

      {environments.isError ? (
        <QueryError error={environments.error} />
      ) : environments.isLoading ? (
        <ListSkeleton />
      ) : all.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No environments yet"
          description="Create one for each stage you run, such as production and staging."
          action={canManage && <Button onClick={() => open('create')}>New environment</Button>}
        />
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
            <SearchInput value={search} onValueChange={setSearch} placeholder="Search environments" aria-label="Search environments" />
            <NativeSelect value={type} onChange={(e) => setType(e.target.value as TypeFilter)} aria-label="Filter by type">
              <option value="all">All environments</option>
              <option value="production">Production only</option>
              <option value="other">Non-production only</option>
            </NativeSelect>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No environments match"
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setSearch('')
                    setType('all')
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
                      <TableHead>Name</TableHead>
                      <TableHead>Protection</TableHead>
                      <TableHead className="text-right">Databases</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead className="w-14">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((env) => (
                      <TableRow key={env.id}>
                        <TableCell className="max-w-80 truncate font-mono font-medium">{env.name}</TableCell>
                        <TableCell>
                          <ProtectionBadge production={env.is_production} />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          <DatabaseCount id={env.id} count={env.datasource_count} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(env.created_at)}>
                          {formatDate(env.created_at)}
                        </TableCell>
                        <TableCell className="text-right">{actionsFor(env)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Phones: cards */}
              <ul className="divide-y md:hidden">
                {filtered.map((env) => (
                  <li key={env.id} className="grid gap-2 p-4">
                    <div className="flex items-start gap-2">
                      <p className="min-w-0 flex-1 truncate pt-1.5 font-mono font-medium">{env.name}</p>
                      <div className="-mr-2">{actionsFor(env)}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                      <ProtectionBadge production={env.is_production} />
                      <DatabaseCount id={env.id} count={env.datasource_count} withLabel />
                      <span className="text-xs text-muted-foreground">Created {formatDate(env.created_at)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {filtered.length > 0 && filtered.length !== all.length && (
            <p className="text-xs text-muted-foreground">
              Showing {filtered.length} of {all.length} environments
            </p>
          )}
        </div>
      )}

      {canManage && (
        <>
          <EnvironmentFormDialog
            open={isOpen('create', 'rename')}
            onOpenChange={close}
            tenantId={tenant.id}
            environment={action?.kind === 'rename' ? target : null}
          />
          <ConfirmDialog
            open={isOpen('protect')}
            onOpenChange={close}
            title={`Mark ${target?.name ?? ''} as production?`}
            description="Its databases get the strictest protection. Only an Owner can remove it again or delete the environment."
            confirmLabel="Mark as production"
            busy={update.isPending}
            error={update.error}
            onConfirm={() => void setProduction(true)}
          />
          <ConfirmDialog
            open={isOpen('unprotect')}
            onOpenChange={close}
            title={`Remove production protection from ${target?.name ?? ''}?`}
            description="Its databases will be treated like staging or development. Do this only if no live customer data is there."
            confirmLabel="Remove protection"
            destructive
            busy={update.isPending}
            error={update.error}
            onConfirm={() => void setProduction(false)}
          />
          <ConfirmDialog
            open={isOpen('delete')}
            onOpenChange={close}
            title={`Delete ${target?.name ?? ''}?`}
            description="Environment roles given to members for it are removed too. Its history stays in the audit log. This cannot be undone."
            confirmLabel="Delete environment"
            destructive
            busy={remove.isPending}
            error={remove.error}
            onConfirm={() => void deleteEnvironment()}
          />
        </>
      )}
    </>
  )
}

function ProtectionBadge({ production }: { production: boolean }) {
  return production ? <Badge variant="warning">Production</Badge> : <Badge variant="secondary">Standard</Badge>
}

function DatabaseCount({ id, count, withLabel = false }: { id: string; count: number; withLabel?: boolean }) {
  const text = withLabel ? `${count} database${count === 1 ? '' : 's'}` : String(count)
  if (count === 0) return <span className="text-muted-foreground">{text}</span>
  return (
    <Link to={`../databases?environmentId=${id}`} className="font-medium text-primary underline-offset-4 hover:underline">
      {text}
    </Link>
  )
}

function ListSkeleton() {
  return (
    <div className="grid gap-4" aria-busy aria-label="Loading environments">
      <Skeleton className="h-9 w-full" />
      <Card className="divide-y">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-4 p-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="ml-auto h-4 w-10" />
          </div>
        ))}
      </Card>
    </div>
  )
}