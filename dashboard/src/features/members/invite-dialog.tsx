import { CheckCircle2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { CopyField } from '@/components/copy-field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { useCreateInvitation } from '@/features/members/api'
import { RolePicker } from '@/features/members/role-picker'
import { describeError, fieldErrors } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { InvitationCreated, Role } from '@/lib/types'

/** The link the invited person opens. The token sits after '#', so it never reaches any server log. */
function inviteLink(token: string): string {
  return `${window.location.origin}/invite#${token}`
}

export function InviteDialog({
  open,
  onOpenChange,
  tenantId,
  tenantName,
  roles,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  tenantName: string
  roles: Role[]
}) {
  // A new form every time the dialog opens, so an old link is never shown again.
  const [round, setRound] = useState(0)
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (o) setRound((r) => r + 1)
        onOpenChange(o)
      }}
    >
      <DialogContent>
        {open && (
          <InviteFlow key={round} tenantId={tenantId} tenantName={tenantName} roles={roles} onDone={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function defaultRoleId(roles: Role[]): string {
  // The least powerful role is the safe default.
  return (roles.find((r) => r.key === 'viewer') ?? roles.at(-1))?.id ?? ''
}

function InviteFlow({
  tenantId,
  tenantName,
  roles,
  onDone,
}: {
  tenantId: string
  tenantName: string
  roles: Role[]
  onDone: () => void
}) {
  const create = useCreateInvitation(tenantId)
  const [email, setEmail] = useState('')
  const [roleId, setRoleId] = useState(() => defaultRoleId(roles))
  const [created, setCreated] = useState<InvitationCreated | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const result = await create.mutateAsync({ email: email.trim(), role_id: roleId }).catch(() => null)
    if (result) setCreated(result)
  }

  if (created) {
    return (
      <div className="grid gap-4">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-5 text-success" aria-hidden />
            Invitation ready
          </DialogTitle>
          <DialogDescription>
            Send this link to <span className="font-medium text-foreground">{created.email}</span>. They join {tenantName} as{' '}
            {created.role.name} after signing in with that email.
          </DialogDescription>
        </DialogHeader>
        <CopyField value={inviteLink(created.token)} label="Invitation link" />
        <Alert variant="warning">
          <AlertDescription>
            This link is shown only once and works until {formatDateTime(created.expires_at)}. If it gets lost, invite the
            same email again for a new link.
          </AlertDescription>
        </Alert>
        <DialogFooter>
          <Button onClick={onDone}>Done</Button>
        </DialogFooter>
      </div>
    )
  }

  const errors = fieldErrors(create.error)
  const generalError = create.isError && !errors.email

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Invite a member</DialogTitle>
        <DialogDescription>They get a link to join {tenantName}. You can change their role later.</DialogDescription>
      </DialogHeader>

      {generalError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(create.error)}</AlertDescription>
        </Alert>
      )}

      <Field
        label="Email"
        type="email"
        autoComplete="off"
        placeholder="name@company.com"
        required
        autoFocus
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={errors.email}
      />

      <div className="grid gap-2">
        <p id="invite-role-label" className="text-sm font-medium leading-none">
          Role
        </p>
        <div className="max-h-[40vh] overflow-y-auto pr-1">
          <RolePicker name="invite-role" labelledBy="invite-role-label" roles={roles} value={roleId} onChange={setRoleId} disabled={create.isPending} />
        </div>
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={create.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={create.isPending} disabled={!email.trim() || !roleId}>
          Create invitation
        </Button>
      </DialogFooter>
    </form>
  )
}