import { CheckCircle2, Download, KeyRound, MousePointerClick, Server, Terminal } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { CodeBlock } from '@/components/code-block'
import { CopyField } from '@/components/copy-field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useConnector } from '@/features/connectors/api'
import { connectionCode } from '@/features/connectors/connection-code'
import { formatDateTime } from '@/lib/format'
import type { Connector, Enrollment } from '@/lib/types'

/** Where the dashboard serves the Windows connector (built by connector/scripts/build-windows.ps1). */
const WINDOWS_DOWNLOAD = '/downloads/zipzy-connector.exe'

/** Whether this server actually has the .exe to hand out (it is built locally, not committed). */
function useDownloadAvailable(): boolean | null {
  const [available, setAvailable] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    fetch(WINDOWS_DOWNLOAD, { method: 'HEAD' })
      .then((r) => alive && setAvailable(r.ok && !r.headers.get('content-type')?.includes('text/html')))
      .catch(() => alive && setAvailable(false))
    return () => {
      alive = false
    }
  }, [])
  return available
}

/**
 * How to install a connector, with its one-time code. Watches the connector and switches to
 * "Connected" by itself as soon as the program checks in.
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
  const download = useDownloadAvailable()
  const code = connectionCode(window.location.origin, enrollment.token)

  if (status !== 'pending') {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-6 text-center">
        <CheckCircle2 className="size-8 text-success" aria-hidden />
        <p className="font-medium">{connector.name} is connected</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Its database now appears under Databases, with health, tables and indexes.
        </p>
      </div>
    )
  }

  const expiry = (
    <Alert variant="warning" className="mt-2">
      <AlertDescription>
        Shown only once and works until {formatDateTime(enrollment.expires_at)}. If it is lost or expires, choose “New
        install command” from the connector’s menu.
      </AlertDescription>
    </Alert>
  )

  return (
    <div className="grid gap-4">
      <Tabs defaultValue="windows">
        <TabsList aria-label="Where the connector runs" className="mb-4">
          <TabsTrigger value="windows">Windows computer</TabsTrigger>
          <TabsTrigger value="docker">Server with Docker</TabsTrigger>
        </TabsList>

        <TabsContent value="windows">
          <ol className="grid gap-4">
            <Step n={1} icon={Download} title="Download the connector">
              Use a computer that can reach your database. One file, nothing to install.
              <div className="mt-2">
                {download === false ? (
                  <p className="text-xs">The download is not available on this server yet. Ask your ZipZy administrator.</p>
                ) : (
                  <Button asChild size="sm" variant="outline" disabled={download === null}>
                    <a href={WINDOWS_DOWNLOAD} download="zipzy-connector.exe">
                      <Download />
                      zipzy-connector.exe
                    </a>
                  </Button>
                )}
              </div>
            </Step>
            <Step n={2} icon={KeyRound} title="Copy your connection code">
              <CopyField value={code} label="Connection code" className="mt-2" />
              {expiry}
            </Step>
            <Step n={3} icon={MousePointerClick} title="Open the file and paste the code">
              It then asks which database to watch and for a read-only user’s password, tests it and connects. If Windows
              warns about an unknown app, choose “More info” and then “Run anyway”.
            </Step>
          </ol>
        </TabsContent>

        <TabsContent value="docker">
          <ol className="grid gap-4">
            <Step n={1} icon={Server} title="Pick a server inside your network">
              It must reach your databases and have Docker installed. Nothing needs to be opened to the internet: the
              connector only makes outgoing connections.
            </Step>
            <Step n={2} icon={Terminal} title="Run this command on that server">
              <CodeBlock code={enrollment.command} label="Install command" className="mt-2" />
              {expiry}
            </Step>
          </ol>
        </TabsContent>
      </Tabs>

      <p className="flex items-center gap-3 rounded-lg bg-muted px-3 py-2.5 text-sm text-muted-foreground" aria-live="polite">
        <Spinner className="size-4" />
        Waiting for the connector to check in. This updates by itself.
      </p>
    </div>
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
