import { useState, type FormEvent } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { useCreateConnector } from '@/features/connectors/api'
import { InstallSteps } from '@/features/connectors/install-steps'
import { describeError, fieldErrors } from '@/lib/api'
import type { ConnectorCreated } from '@/lib/types'

/** Name a new connector, then show how to install it. */
export function AddConnectorDialog({
  open,
  onOpenChange,
  tenantId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
}) {
  // A fresh form each time the dialog opens, so an old install command is never shown again.
  const [round, setRound] = useState(0)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setRound((r) => r + 1)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <AddConnectorFlow key={round} tenantId={tenantId} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function AddConnectorFlow({ tenantId, onDone }: { tenantId: string; onDone: () => void }) {
  const create = useCreateConnector(tenantId)
  const [name, setName] = useState('')
  const [created, setCreated] = useState<ConnectorCreated | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const result = await create.mutateAsync(name.trim()).catch(() => null)
    if (result) setCreated(result)
  }

  if (created) {
    return (
      <div className="grid gap-5">
        <DialogHeader>
          <DialogTitle>Install {created.connector.name}</DialogTitle>
          <DialogDescription>A few clicks on a computer near your database. Its passwords stay there.</DialogDescription>
        </DialogHeader>
        <InstallSteps tenantId={tenantId} connector={created.connector} enrollment={created.enrollment} />
        <DialogFooter>
          <Button onClick={onDone}>Done</Button>
        </DialogFooter>
      </div>
    )
  }

  const errors = fieldErrors(create.error)
  const generalError = create.isError && !errors.name

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Add a connector</DialogTitle>
        <DialogDescription>
          A small program you run inside your own network. It reaches your databases and sends us only health and
          performance information.
        </DialogDescription>
      </DialogHeader>

      {generalError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(create.error)}</AlertDescription>
        </Alert>
      )}

      <Field
        label="Name"
        placeholder="e.g. Mumbai office server"
        hint="Where it runs, so your team can tell connectors apart."
        autoFocus
        autoComplete="off"
        maxLength={100}
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={errors.name}
      />

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={create.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={create.isPending} disabled={!name.trim()}>
          Continue
        </Button>
      </DialogFooter>
    </form>
  )
}
