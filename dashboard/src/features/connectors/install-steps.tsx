import { CheckCircle2, Server, Terminal } from 'lucide-react'
import type { ReactNode } from 'react'

import { CodeBlock } from '@/components/code-block'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Spinner } from '@/components/ui/spinner'
import { useConnector } from '@/features/connectors/api'
import { formatDateTime } from '@/lib/format'
import type { Connector, Enrollment } from '@/lib/types'

/**
 * How to install a connector, with its one-time command. Watches the connector and
 * switches to "Connected" by itself as soon as the program checks in.
 */
export function InstallSteps({
  tenantId,
  connector,
  enrollment,
}: {
  tenantId: string
  connector: Connector
  enrollment: Enrollment
}) {
  const live = useConnector(tenantId, connector.id, { watch: true })
  const status = live.data?.status ?? connector.status

  if (status !== 'pending') {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-6 text-center">
        <CheckCircle2 className="size-8 text-success" aria-hidden />
        <p className="font-medium">{connector.name} is installed</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          The connector checked in. You can now add the databases it can reach.
        </p>
      </div>
    )
  }

  return (
    <ol className="grid gap-4">
      <Step n={1} icon={Server} title="Pick a server inside your network">
        It must reach your databases and have Docker installed. Nothing needs to be opened to the internet: the connector
        only makes outgoing connections.
      </Step>
      <Step n={2} icon={Terminal} title="Run this command on that server">
        <CodeBlock code={enrollment.command} label="Install command" className="mt-2" />
        <Alert variant="warning" className="mt-2">
          <AlertDescription>
            Shown only once and works until {formatDateTime(enrollment.expires_at)}. If it is lost or expires, choose
            “New install command” from the connector’s menu.
          </AlertDescription>
        </Alert>
      </Step>
      <li className="flex items-center gap-3 rounded-lg bg-muted px-3 py-2.5 text-sm text-muted-foreground" aria-live="polite">
        <Spinner className="size-4" />
        Waiting for the connector to check in. This updates by itself.
      </li>
    </ol>
  )
}

function Step({
  n,
  icon: Icon,
  title,
  children,
}: {
  n: number
  icon: typeof Server
  title: string
  children: ReactNode
}) {
  return (
    <li className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3">
      <span className="grid size-8 place-items-center rounded-full bg-accent text-accent-foreground" aria-hidden>
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">
          <span className="sr-only">Step {n}: </span>
          {title}
        </p>
        <div className="mt-1 text-sm text-muted-foreground">{children}</div>
      </div>
    </li>
  )
}