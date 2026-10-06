import { FileCog, PlugZap, Radar } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/**
 * Databases are never typed into the dashboard: the connector on the customer's server
 * reports them. This explains how, so nobody looks for a password field that does not exist.
 */
export function AddDatabaseHelp({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a database</DialogTitle>
          <DialogDescription>
            Databases are added on your own server, not here. That way their passwords never leave your network.
          </DialogDescription>
        </DialogHeader>
        <ol className="grid gap-4">
          <Step icon={PlugZap} title="Have a connector running">
            Install one on a server that can reach the database.{' '}
            <Link to="../connectors" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => onOpenChange(false)}>
              Go to connectors
            </Link>
          </Step>
          <Step icon={FileCog} title="List the database in the connector’s settings file">
            On that server, add it to <code className="rounded bg-muted px-1 font-mono text-xs">/etc/zipzy/connector.yaml</code>{' '}
            with a read-only monitoring user. The password stays in that file.
          </Step>
          <Step icon={Radar} title="It appears here by itself">
            Within a minute. New databases start in production, the strictest environment, unless the file names another
            one. You can move them afterwards.
          </Step>
        </ol>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>Got it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Step({ icon: Icon, title, children }: { icon: typeof PlugZap; title: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3">
      <span className="grid size-8 place-items-center rounded-full bg-accent text-accent-foreground" aria-hidden>
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{children}</p>
      </div>
    </li>
  )
}