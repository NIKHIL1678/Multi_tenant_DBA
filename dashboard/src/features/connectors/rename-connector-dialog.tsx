import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { useRenameConnector } from '@/features/connectors/api'
import { describeError, fieldErrors } from '@/lib/api'
import type { Connector } from '@/lib/types'

export function RenameConnectorDialog({
  open,
  onOpenChange,
  tenantId,
  connector,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  connector: Connector | null
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {connector && open && (
          <RenameForm key={connector.id} tenantId={tenantId} connector={connector} onDone={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function RenameForm({ tenantId, connector, onDone }: { tenantId: string; connector: Connector; onDone: () => void }) {
  const rename = useRenameConnector(tenantId)
  const [name, setName] = useState(connector.name)
  const clean = name.trim()

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const result = await rename.mutateAsync({ id: connector.id, name: clean }).catch(() => null)
    if (!result) return
    toast.success(`Renamed to ${result.name}`)
    onDone()
  }

  const errors = fieldErrors(rename.error)
  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Rename connector</DialogTitle>
        <DialogDescription>Only the label changes. The running program is not affected.</DialogDescription>
      </DialogHeader>
      {rename.isError && !errors.name && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(rename.error)}</AlertDescription>
        </Alert>
      )}
      <Field label="Name" autoFocus maxLength={100} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={rename.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={rename.isPending} disabled={!clean || clean === connector.name}>
          Save name
        </Button>
      </DialogFooter>
    </form>
  )
}