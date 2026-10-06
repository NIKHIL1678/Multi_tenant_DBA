import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useUpdateMember } from '@/features/members/api'
import { RolePicker } from '@/features/members/role-picker'
import { describeError } from '@/lib/api'
import type { Member, Role } from '@/lib/types'

export function ChangeRoleDialog({
  member,
  open,
  onOpenChange,
  tenantId,
  roles,
}: {
  member: Member | null
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  roles: Role[]
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {member && (
          <ChangeRoleForm key={member.id} member={member} tenantId={tenantId} roles={roles} onDone={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function ChangeRoleForm({
  member,
  tenantId,
  roles,
  onDone,
}: {
  member: Member
  tenantId: string
  roles: Role[]
  onDone: () => void
}) {
  const [roleId, setRoleId] = useState(member.role.id)
  const update = useUpdateMember(tenantId)
  const who = member.full_name ?? member.email

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const updated = await update.mutateAsync({ memberId: member.id, role_id: roleId }).catch(() => null)
    if (!updated) return
    toast.success(`${who} is now ${updated.role.name}`)
    onDone()
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Change role</DialogTitle>
        <DialogDescription>
          Company-wide role for <span className="font-medium text-foreground">{who}</span>. Environment roles, if any, still
          apply inside those environments.
        </DialogDescription>
      </DialogHeader>

      {update.isError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(update.error)}</AlertDescription>
        </Alert>
      )}

      <div className="max-h-[50vh] overflow-y-auto pr-1">
        <RolePicker name="company-role" roles={roles} value={roleId} onChange={setRoleId} disabled={update.isPending} />
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={update.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={update.isPending} disabled={roleId === member.role.id}>
          Save role
        </Button>
      </DialogFooter>
    </form>
  )
}