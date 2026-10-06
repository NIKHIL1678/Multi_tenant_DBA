import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { ENV_NAME_PATTERN, useCreateEnvironment, useUpdateEnvironment } from '@/features/environments/api'
import { describeError, fieldErrors } from '@/lib/api'
import type { Environment } from '@/lib/types'

const NAME_HINT = "Lowercase letters, digits, '-' or '_'. For example: staging-eu"

/** Create a new environment, or rename an existing one (`environment` set). */
export function EnvironmentFormDialog({
  open,
  onOpenChange,
  tenantId,
  environment,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenantId: string
  environment: Environment | null
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {open && (
          <EnvironmentForm
            key={environment?.id ?? 'new'}
            tenantId={tenantId}
            environment={environment}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function EnvironmentForm({
  tenantId,
  environment,
  onDone,
}: {
  tenantId: string
  environment: Environment | null
  onDone: () => void
}) {
  const editing = environment !== null
  const create = useCreateEnvironment(tenantId)
  const update = useUpdateEnvironment(tenantId)
  const mutation = editing ? update : create

  const [name, setName] = useState(environment?.name ?? '')
  const [isProduction, setIsProduction] = useState(false)
  const [touched, setTouched] = useState(false)

  const clean = name.trim()
  const localError = touched && clean !== '' && !ENV_NAME_PATTERN.test(clean) ? NAME_HINT : undefined
  const serverErrors = fieldErrors(mutation.error)
  const generalError = mutation.isError && !serverErrors.name

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (!ENV_NAME_PATTERN.test(clean)) return
    const result = editing
      ? await update.mutateAsync({ id: environment.id, name: clean }).catch(() => null)
      : await create.mutateAsync({ name: clean, is_production: isProduction }).catch(() => null)
    if (!result) return
    toast.success(editing ? `Renamed to ${result.name}` : `${result.name} created`)
    onDone()
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4" noValidate>
      <DialogHeader>
        <DialogTitle>{editing ? 'Rename environment' : 'New environment'}</DialogTitle>
        <DialogDescription>
          {editing
            ? 'Databases, roles and history stay with the environment; only its name changes.'
            : 'Group databases that belong together, such as staging or a regional production.'}
        </DialogDescription>
      </DialogHeader>

      {generalError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(mutation.error)}</AlertDescription>
        </Alert>
      )}

      <Field
        label="Name"
        placeholder="staging-eu"
        autoFocus
        autoComplete="off"
        spellCheck={false}
        maxLength={60}
        className="[&_input]:font-mono"
        value={name}
        // Names are lowercase: convert as the user types instead of complaining afterwards.
        onChange={(e) => setName(e.target.value.toLowerCase().replaceAll(' ', '-'))}
        onBlur={() => setTouched(true)}
        error={localError ?? serverErrors.name}
        hint={NAME_HINT}
      />

      {!editing && (
        <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
          <div className="grid gap-1">
            <Label htmlFor="env-production">Production</Label>
            <p className="text-xs text-muted-foreground">
              Strictest protection. Only an Owner can remove it or delete the environment later.
            </p>
          </div>
          <Switch id="env-production" checked={isProduction} onCheckedChange={setIsProduction} />
        </div>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button type="submit" busy={mutation.isPending} disabled={!clean || (editing && clean === environment.name)}>
          {editing ? 'Save name' : 'Create environment'}
        </Button>
      </DialogFooter>
    </form>
  )
}