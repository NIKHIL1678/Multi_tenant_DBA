import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useNewEnrollmentToken } from '@/features/connectors/api'
import { InstallSteps } from '@/features/connectors/install-steps'
import { describeError } from '@/lib/api'
import type { Connector } from '@/lib/types'

/** Issue a fresh install command for a connector that is still waiting. The previous one stops working. */
export function NewCommandDialog({
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
      <DialogContent className="sm:max-w-2xl">
        {connector && open && (
          <NewCommand key={connector.id} tenantId={tenantId} connector={connector} onDone={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function NewCommand({ tenantId, connector, onDone }: { tenantId: string; connector: Connector; onDone: () => void }) {
  const issue = useNewEnrollmentToken(tenantId)

  if (issue.data) {
    return (
      <div className="grid gap-5">
        <DialogHeader>
          <DialogTitle>Install {connector.name}</DialogTitle>
          <DialogDescription>Any earlier install command for this connector no longer works.</DialogDescription>
        </DialogHeader>
        <InstallSteps tenantId={tenantId} connector={connector} enrollment={issue.data} />
        <DialogFooter>
          <Button onClick={onDone}>Done</Button>
        </DialogFooter>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <DialogHeader>
        <DialogTitle>New install command</DialogTitle>
        <DialogDescription>
          Use this if the command for <span className="font-medium text-foreground">{connector.name}</span> was lost or
          has expired. The previous command stops working straight away.
        </DialogDescription>
      </DialogHeader>
      {issue.isError && (
        <Alert variant="destructive">
          <AlertDescription>{describeError(issue.error)}</AlertDescription>
        </Alert>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onDone} disabled={issue.isPending}>
          Cancel
        </Button>
        <Button onClick={() => issue.mutate(connector.id)} busy={issue.isPending}>
          Create new command
        </Button>
      </DialogFooter>
    </div>
  )
}