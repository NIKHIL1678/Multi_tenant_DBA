import { Layers } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/empty-state'
import { QueryError } from '@/components/query-error'
import { SearchInput } from '@/components/search-input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { useEnvironments } from '@/features/environments/api'
import { useRemoveEnvironmentRole, useSetEnvironmentRole } from '@/features/members/api'
import { describeError } from '@/lib/api'
import type { Environment, Member, Role } from '@/lib/types'

const SEARCH_FROM = 8 // show a search box once there are more environments than this

/**
 * Give a member a different role inside particular environments.
 * Example: Viewer company-wide, but DBA in staging.
 */
export function EnvironmentAccessDialog({
  member,
  open,
  onOpenChange,
  tenantId,
  roles,
  assignableRoles,
}: {
  member: Member | null
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  roles: Role[]
  assignableRoles: Role[]
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        {member && (
          <EnvironmentAccess
            key={member.id}
            member={member}
            tenantId={tenantId}
            roles={roles}
            assignableRoles={assignableRoles}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function EnvironmentAccess({
  member,
  tenantId,
  roles,
  assignableRoles,
  onDone,
}: {
  member: Member
  tenantId: string
  roles: Role[]
  assignableRoles: Role[]
  onDone: () => void
}) {
  const environments = useEnvironments(tenantId)
  const setRole = useSetEnvironmentRole(tenantId)
  const removeRole = useRemoveEnvironmentRole(tenantId)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [search, setSearch] = useState('')

  const who = member.full_name ?? member.email
  const overrides = new Map(member.environment_roles.map((er) => [er.environment_id, er.role]))
  const assignableIds = new Set(assignableRoles.map((r) => r.id))

  async function change(env: Environment, roleId: string) {
    setSavingId(env.id)
    setError(null)
    try {
      if (roleId === '') {
        await removeRole.mutateAsync({ memberId: member.id, environmentId: env.id })
        toast.success(`${env.name}: back to the company role`)
      } else {
        const updated = await setRole.mutateAsync({ memberId: member.id, environmentId: env.id, roleId })
        const role = updated.environment_roles.find((er) => er.environment_id === env.id)?.role
        toast.success(`${env.name}: ${role?.name ?? 'role'} set`)
      }
    } catch (err) {
      setError(err)
    } finally {
      setSavingId(null)
    }
  }

  const all = environments.data ?? []
  const q = search.trim().toLowerCase()
  const shown = q ? all.filter((e) => e.name.includes(q)) : all

  return (
    <div className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Environment access</DialogTitle>
        <DialogDescription>
          <span className="font-medium text-foreground">{who}</span> is {member.role.name} across the company. Pick a
          different role for any environment where they need more or less access.
        </DialogDescription>
      </DialogHeader>

      {error != null && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(error)}</AlertDescription>
        </Alert>
      )}

      {all.length > SEARCH_FROM && (
        <SearchInput value={search} onValueChange={setSearch} placeholder="Find an environment" aria-label="Find an environment" />
      )}

      <div className="max-h-[50vh] overflow-y-auto rounded-lg border">
        {environments.isLoading ? (
          <div className="grid gap-2 p-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : environments.isError ? (
          <div className="p-3">
            <QueryError error={environments.error} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon={Layers}
            title={q ? 'No environment matches' : 'No environments yet'}
            className="m-3 border-0"
          />
        ) : (
          <ul className="divide-y">
            {shown.map((env) => {
              const override = overrides.get(env.id)
              // You cannot remove or change an override that has more access than you.
              const locked = override !== undefined && !assignableIds.has(override.id)
              const selectId = `env-role-${env.id}`
              return (
                <li key={env.id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <label htmlFor={selectId} className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-mono text-sm">{env.name}</span>
                    {env.is_production && <Badge variant="warning">Production</Badge>}
                    {override && <Badge variant="outline">Custom</Badge>}
                  </label>
                  <NativeSelect
                    id={selectId}
                    className="sm:w-56"
                    value={override?.id ?? ''}
                    disabled={savingId !== null || locked}
                    onChange={(e) => void change(env, e.target.value)}
                    aria-busy={savingId === env.id || undefined}
                  >
                    <option value="">Company role ({member.role.name})</option>
                    {roles
                      .filter((r) => assignableIds.has(r.id) || r.id === override?.id)
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                  </NativeSelect>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <DialogFooter>
        <Button type="button" onClick={onDone} disabled={savingId !== null}>
          Done
        </Button>
      </DialogFooter>
    </div>
  )
}