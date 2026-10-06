import { SearchX, Users } from 'lucide-react'
import { useMemo, useState } from 'react'

import { EmptyState } from '@/components/empty-state'
import { SearchInput } from '@/components/search-input'
import { UserAvatar } from '@/components/user-avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { roleBadgeVariant, type MemberAccess } from '@/features/members/access'
import { MemberActions, type MemberActionKind } from '@/features/members/member-actions'
import { formatDate, formatDateTime } from '@/lib/format'
import type { Member } from '@/lib/types'
import { cn } from '@/lib/utils'

type StatusFilter = 'all' | 'active' | 'suspended'

function sortMembers(a: Member, b: Member): number {
  if (a.status !== b.status) return a.status === 'active' ? -1 : 1
  return (a.full_name ?? a.email).localeCompare(b.full_name ?? b.email)
}

/**
 * Members as a table on wide screens and as cards on phones.
 * Both views come from the same filtered list, so they always agree.
 */
export function MembersList({
  members,
  isLoading,
  access,
  meId,
  onAction,
}: {
  members: Member[] | undefined
  isLoading: boolean
  access: MemberAccess
  meId: string
  onAction: (kind: MemberActionKind, member: Member) => void
}) {
  const [search, setSearch] = useState('')
  const [roleId, setRoleId] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (members ?? [])
      .filter(
        (m) =>
          (!q || m.email.toLowerCase().includes(q) || (m.full_name ?? '').toLowerCase().includes(q)) &&
          (!roleId || m.role.id === roleId) &&
          (status === 'all' || m.status === status),
      )
      .sort(sortMembers)
  }, [members, search, roleId, status])

  const filtering = search !== '' || roleId !== '' || status !== 'all'
  const clear = () => {
    setSearch('')
    setRoleId('')
    setStatus('all')
  }

  if (isLoading) return <ListSkeleton />
  if (!members || members.length === 0) {
    return <EmptyState icon={Users} title="No members yet" description="Invite your team to start working together." />
  }

  const actionsFor = (m: Member) =>
    access.canManage(m) ? <MemberActions member={m} isMe={m.user_id === meId} onAction={onAction} /> : null

  return (
    <div className="grid gap-4">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_11rem_10rem]">
        <SearchInput value={search} onValueChange={setSearch} placeholder="Search by name or email" aria-label="Search members" />
        <div className="grid grid-cols-2 gap-2 sm:contents">
          <NativeSelect value={roleId} onChange={(e) => setRoleId(e.target.value)} aria-label="Filter by role">
            <option value="">All roles</option>
            {access.roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label="Filter by status">
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </NativeSelect>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={SearchX}
          title="No members match"
          description="Try a different name, role or status."
          action={
            <Button variant="outline" onClick={clear}>
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
                  <TableHead>Member</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="w-14">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <Identity member={m} isMe={m.user_id === meId} />
                    </TableCell>
                    <TableCell>
                      <RoleSummary member={m} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={m.status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(m.joined_at)}>
                      {formatDate(m.joined_at)}
                    </TableCell>
                    <TableCell className="text-right">{actionsFor(m)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Phones: cards */}
          <ul className="divide-y md:hidden">
            {filtered.map((m) => (
              <li key={m.id} className="grid gap-3 p-4">
                <div className="flex items-start gap-2">
                  <Identity member={m} isMe={m.user_id === meId} className="flex-1" />
                  <div className="-mt-1 -mr-2">{actionsFor(m)}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2 pl-12">
                  <RoleSummary member={m} />
                  <StatusBadge status={m.status} />
                </div>
                <p className="pl-12 text-xs text-muted-foreground">Joined {formatDate(m.joined_at)}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {filtering && filtered.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Showing {filtered.length} of {members.length} members
        </p>
      )}
    </div>
  )
}

function Identity({ member, isMe, className }: { member: Member; isMe: boolean; className?: string }) {
  const name = member.full_name ?? member.email
  return (
    <div className={cn('flex min-w-0 items-center gap-3', member.status === 'suspended' && 'opacity-60', className)}>
      <UserAvatar name={name} />
      <div className="min-w-0">
        <p className="flex items-center gap-2 truncate font-medium">
          <span className="truncate">{name}</span>
          {isMe && <Badge variant="outline">You</Badge>}
        </p>
        {member.full_name && <p className="truncate text-sm text-muted-foreground">{member.email}</p>}
      </div>
    </div>
  )
}

function RoleSummary({ member }: { member: Member }) {
  const extra = member.environment_roles
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant={roleBadgeVariant(member.role.key)}>{member.role.name}</Badge>
      {extra.length > 0 && (
        <Badge variant="outline" title={extra.map((er) => `${er.environment_name}: ${er.role.name}`).join('\n')}>
          +{extra.length} environment {extra.length === 1 ? 'role' : 'roles'}
        </Badge>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  return status === 'active' ? <Badge variant="success">Active</Badge> : <Badge variant="warning">Suspended</Badge>
}

function ListSkeleton() {
  return (
    <div className="grid gap-4" aria-busy aria-label="Loading members">
      <Skeleton className="h-9 w-full" />
      <Card className="divide-y">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 p-4">
            <Skeleton className="size-9 rounded-full" />
            <div className="grid flex-1 gap-2">
              <Skeleton className="h-4 w-40 max-w-full" />
              <Skeleton className="h-3 w-56 max-w-full" />
            </div>
            <Skeleton className="hidden h-5 w-16 sm:block" />
          </div>
        ))}
      </Card>
    </div>
  )
}