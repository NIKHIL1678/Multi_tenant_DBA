import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { useMoveDatasource } from '@/features/datasources/api'
import { describeError } from '@/lib/api'
import type { Datasource, Environment } from '@/lib/types'

/** Move a database to another environment. Leaving production needs an Owner. */
export function MoveDialog({
  open,
  onOpenChange,
  tenantId,
  datasource,
  environments,
  isOwner,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  datasource: Datasource | null
  environments: Environment[]
  isOwner: boolean
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {datasource && open && (
          <MoveForm
            key={datasource.id}
            tenantId={tenantId}
            datasource={datasource}
            environments={environments}
            isOwner={isOwner}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function MoveForm({
  tenantId,
  datasource: ds,
  environments,
  isOwner,
  onDone,
}: {
  tenantId: string
  datasource: Datasource
  environments: Environment[]
  isOwner: boolean
  onDone: () => void
}) {
  const move = useMoveDatasource(tenantId)
  const [targetId, setTargetId] = useState('')
  const target = environments.find((e) => e.id === targetId)
  const leavingProduction = ds.environment.is_production && target !== undefined && !target.is_production
  const enteringProduction = !ds.environment.is_production && target?.is_production === true
  const blocked = leavingProduction && !isOwner

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!target || blocked) return
    const moved = await move.mutateAsync({ id: ds.id, environmentId: target.id }).catch(() => null)
    if (!moved) return
    toast.success(`${ds.local_name} moved to ${moved.environment.name}`)
    onDone()
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Move {ds.local_name}</DialogTitle>
        <DialogDescription>
          It is in <span className="font-mono text-foreground">{ds.environment.name}</span> now. Who may see and change it
          follows the environment it is in.
        </DialogDescription>
      </DialogHeader>

      {move.isError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(move.error)}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-2">
        <Label htmlFor="move-target">Move to</Label>
        <NativeSelect id="move-target" value={targetId} onChange={(e) => setTargetId(e.target.value)} required>
          <option value="" disabled>
            Choose an environment
          </option>
          {environments
            .filter((e) => e.id !== ds.environment.id)
            .map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
                {e.is_production ? ' (production)' : ''}
              </option>
            ))}
        </NativeSelect>
      </div>

      {leavingProduction && (
        <Alert variant={blocked ? 'destructive' : 'warning'}>
          <AlertDescription>
            {blocked
              ? 'Only an Owner can take a database out of production.'
              : 'It leaves production and loses production protection. Do this only if it holds no live customer data.'}
          </AlertDescription>
        </Alert>
      )}
      {enteringProduction && (
        <Alert variant="warning">
          <AlertDescription>It gets production protection. Only an Owner can take it out again.</AlertDescription>
        </Alert>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={move.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={move.isPending} disabled={!target || blocked}>
          Move database
        </Button>
      </DialogFooter>
    </form>
  )
}