import { MailPlus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState } from '@/components/empty-state'
import { QueryError } from '@/components/query-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useInvitations, useRevokeInvitation } from '@/features/members/api'
import { roleBadgeVariant } from '@/features/members/access'
import { formatDateTime, formatRelative } from '@/lib/format'
import type { Invitation, Role } from '@/lib/types'
import { useNow } from '@/lib/use-now'

const DAY_MS = 24 * 3600 * 1000

/** Pending invitations: who was invited, as what, and until when the link works. */
export function InvitationsList({
  tenantId,
  assignableRoles,
  onInvite,
}: {
  tenantId: string
  assignableRoles: Role[]
  onInvite: () => void
}) {
  const invitations = useInvitations(tenantId, { enabled: true })
  const revoke = useRevokeInvitation(tenantId)
  const [target, setTarget] = useState<Invitation | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const mayRevoke = new Set(assignableRoles.map((r) => r.id))

  function ask(inv: Invitation) {
    revoke.reset()
    setTarget(inv)
    setConfirmOpen(true)
  }

  async function confirm() {
    if (!target) return
    const ok = await revoke.mutateAsync(target.id).then(
      () => true,
      () => false,
    )
    if (!ok) return
    toast.success(`Invitation for ${target.email} cancelled`)
    setConfirmOpen(false)
  }

  if (invitations.isLoading) {
    return (
      <Card className="divide-y">
        {[0, 1].map((i) => (
          <div key={i} className="flex items-center gap-3 p-4">
            <div className="grid flex-1 gap-2">
              <Skeleton className="h-4 w-48 max-w-full" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
        ))}
      </Card>
    )
  }
  if (invitations.isError) return <QueryError error={invitations.error} />

  const list = invitations.data ?? []
  if (list.length === 0) {
    return (
      <EmptyState
        icon={MailPlus}
        title="No pending invitations"
        description="Invitations you send appear here until they are accepted, cancelled or expire."
        action={<Button onClick={onInvite}>Invite a member</Button>}
      />
    )
  }

  const revokeButton = (inv: Invitation, compact = false) =>
    mayRevoke.has(inv.role.id) ? (
      <Button
        variant="ghost"
        size={compact ? 'icon' : 'sm'}
        onClick={() => ask(inv)}
        aria-label={`Cancel invitation for ${inv.email}`}
        className="text-destructive hover:bg-danger-soft hover:text-destructive"
      >
        <Trash2 />
        {!compact && 'Cancel'}
      </Button>
    ) : null

  return (
    <>
      <Card className="overflow-hidden">
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Invited by</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="w-24">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="max-w-72 truncate font-medium">{inv.email}</TableCell>
                  <TableCell>
                    <Badge variant={roleBadgeVariant(inv.role.key)}>{inv.role.name}</Badge>
                  </TableCell>
                  <TableCell className="max-w-56 truncate text-muted-foreground">{inv.invited_by_email ?? '—'}</TableCell>
                  <TableCell>
                    <Expiry iso={inv.expires_at} />
                  </TableCell>
                  <TableCell className="text-right">{revokeButton(inv)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <ul className="divide-y md:hidden">
          {list.map((inv) => (
            <li key={inv.id} className="grid gap-2 p-4">
              <div className="flex items-start gap-2">
                <p className="min-w-0 flex-1 truncate font-medium">{inv.email}</p>
                <div className="-mt-1 -mr-2">{revokeButton(inv, true)}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={roleBadgeVariant(inv.role.key)}>{inv.role.name}</Badge>
                <Expiry iso={inv.expires_at} />
              </div>
              {inv.invited_by_email && (
                <p className="truncate text-xs text-muted-foreground">Invited by {inv.invited_by_email}</p>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Cancel invitation?"
        description={
          <>
            The link sent to <span className="font-medium text-foreground">{target?.email}</span> will stop working.
          </>
        }
        confirmLabel="Cancel invitation"
        destructive
        busy={revoke.isPending}
        error={revoke.error}
        onConfirm={() => void confirm()}
      />
    </>
  )
}

function Expiry({ iso }: { iso: string }) {
  const now = useNow()
  const soon = new Date(iso).getTime() - now < DAY_MS
  return (
    <span title={formatDateTime(iso)} className="text-sm whitespace-nowrap">
      {soon ? <Badge variant="warning">Expires {formatRelative(iso, now)}</Badge> : <span className="text-muted-foreground">{formatRelative(iso, now)}</span>}
    </span>
  )
}