import { UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { Button } from '@/components/ui/button'
import { TabCount, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMemberAccess } from '@/features/members/access'
import { useInvitations, useMembers, useUpdateMember } from '@/features/members/api'
import { ChangeRoleDialog } from '@/features/members/change-role-dialog'
import { EnvironmentAccessDialog } from '@/features/members/environment-access-dialog'
import { InvitationsList } from '@/features/members/invitations-list'
import { InviteDialog } from '@/features/members/invite-dialog'
import type { MemberActionKind } from '@/features/members/member-actions'
import { MembersList } from '@/features/members/members-list'
import { useMe } from '@/lib/auth-context'
import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { Member } from '@/lib/types'

type Tab = 'members' | 'invitations'

/** Open dialog. `open` turns false first so the closing animation still has its content. */
type Action = { kind: MemberActionKind; member: Member; open: boolean }

export function MembersPage() {
  const { tenant, can } = useTenant()
  const me = useMe()
  const canManage = can(Permission.MembersManage)
  const access = useMemberAccess()

  const members = useMembers(tenant.id)
  const invitations = useInvitations(tenant.id, { enabled: canManage })
  const update = useUpdateMember(tenant.id)

  // The open tab lives in the URL (?tab=invitations), so reload and the back button keep it.
  const [params, setParams] = useSearchParams()
  const tab: Tab = canManage && params.get('tab') === 'invitations' ? 'invitations' : 'members'
  const setTab = (next: string) =>
    setParams(
      (p) => {
        if (next === 'invitations') p.set('tab', next)
        else p.delete('tab')
        return p
      },
      { replace: true },
    )

  const [inviteOpen, setInviteOpen] = useState(false)
  const [action, setAction] = useState<Action | null>(null)
  const openAction = (kind: MemberActionKind, member: Member) => {
    update.reset()
    setAction({ kind, member, open: true })
  }
  const closeAction = (open: boolean) => {
    if (!open) setAction((a) => a && { ...a, open: false })
  }
  const isOpen = (kind: MemberActionKind) => action?.kind === kind && action.open
  const memberFor = (kind: MemberActionKind) => (action?.kind === kind ? action.member : null)

  async function changeStatus(status: 'active' | 'suspended') {
    if (!action) return
    const who = action.member.full_name ?? action.member.email
    const done = await update.mutateAsync({ memberId: action.member.id, status }).then(
      () => true,
      () => false,
    )
    if (!done) return
    toast.success(status === 'suspended' ? `${who} is suspended` : `${who} is active again`)
    closeAction(false)
  }

  const who = action ? (action.member.full_name ?? action.member.email) : ''

  return (
    <>
      <PageHeader
        title="Members"
        description={`People in ${tenant.name} and what they can do.`}
        actions={
          canManage && (
            <Button onClick={() => setInviteOpen(true)} disabled={access.isLoading}>
              <UserPlus />
              Invite member
            </Button>
          )
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        {canManage && (
          <TabsList aria-label="Members and invitations">
            <TabsTrigger value="members">
              Members <TabCount>{members.data?.length}</TabCount>
            </TabsTrigger>
            <TabsTrigger value="invitations">
              Pending invitations <TabCount>{invitations.data?.length}</TabCount>
            </TabsTrigger>
          </TabsList>
        )}

        <TabsContent value="members">
          {members.isError ? (
            <QueryError error={members.error} />
          ) : (
            <MembersList
              members={members.data}
              isLoading={members.isLoading || access.isLoading}
              access={access}
              meId={me.id}
              onAction={openAction}
            />
          )}
        </TabsContent>

        {canManage && (
          <TabsContent value="invitations">
            <InvitationsList tenantId={tenant.id} assignableRoles={access.assignableRoles} onInvite={() => setInviteOpen(true)} />
          </TabsContent>
        )}
      </Tabs>

      {canManage && (
        <>
          <InviteDialog
            open={inviteOpen}
            onOpenChange={setInviteOpen}
            tenantId={tenant.id}
            tenantName={tenant.name}
            roles={access.assignableRoles}
          />
          <ChangeRoleDialog
            open={isOpen('role')}
            onOpenChange={closeAction}
            member={memberFor('role')}
            tenantId={tenant.id}
            roles={access.assignableRoles}
          />
          <EnvironmentAccessDialog
            open={isOpen('environments')}
            onOpenChange={closeAction}
            member={memberFor('environments')}
            tenantId={tenant.id}
            roles={access.roles}
            assignableRoles={access.assignableRoles}
          />
          <ConfirmDialog
            open={isOpen('suspend')}
            onOpenChange={closeAction}
            title={`Suspend ${who}?`}
            description={`They lose access to ${tenant.name} straight away. Their history stays in the audit log, and you can reactivate them later.`}
            confirmLabel="Suspend"
            destructive
            busy={update.isPending}
            error={update.error}
            onConfirm={() => void changeStatus('suspended')}
          />
          <ConfirmDialog
            open={isOpen('reactivate')}
            onOpenChange={closeAction}
            title={`Reactivate ${who}?`}
            description={`They get their ${action?.member.role.name ?? ''} access to ${tenant.name} back.`}
            confirmLabel="Reactivate"
            busy={update.isPending}
            error={update.error}
            onConfirm={() => void changeStatus('active')}
          />
        </>
      )}
    </>
  )
}