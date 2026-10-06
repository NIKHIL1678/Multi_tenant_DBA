import { Bot, Building2, ChevronRight, Database, Layers, Mail, PlugZap, User, Users, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { actorName } from '@/features/audit/describe'
import { formatDateTime, formatTime } from '@/lib/format'
import type { AuditEntry } from '@/lib/types'

const AREA_ICONS: Record<string, LucideIcon> = {
  member: Users,
  invitation: Mail,
  environment: Layers,
  connector: PlugZap,
  datasource: Database,
  tenant: Building2,
}

/**
 * One line of the log: who, what, when. Opens to show the raw record (request reference,
 * IP address, exact details), which is what support and auditors ask for.
 */
export function AuditEntryRow({ entry, sentence }: { entry: AuditEntry; sentence: string }) {
  const Icon = AREA_ICONS[entry.action.split('.')[0]] ?? (entry.actor.type === 'user' ? User : Bot)
  const who = actorName(entry)

  return (
    <li>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3 transition-colors outline-none hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:ring-inset sm:px-5 [&::-webkit-details-marker]:hidden">
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-accent text-accent-foreground" aria-hidden>
            <Icon className="size-4" />
          </span>
          <span className="min-w-0 flex-1 text-sm leading-relaxed">
            <span className="font-medium">{who}</span> <span className="text-foreground/90">{sentence}</span>
          </span>
          <time
            dateTime={entry.created_at}
            title={formatDateTime(entry.created_at)}
            className="mt-0.5 shrink-0 text-xs whitespace-nowrap text-muted-foreground tabular-nums"
          >
            {formatTime(entry.created_at)}
          </time>
          <ChevronRight
            className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
            aria-hidden
          />
        </summary>
        <dl className="mx-4 mb-3 grid gap-x-4 gap-y-1.5 rounded-lg bg-muted p-3 text-xs sm:mx-5 sm:ml-16 sm:grid-cols-[8rem_minmax(0,1fr)]">
          <Fact label="When">{formatDateTime(entry.created_at)}</Fact>
          <Fact label="Action">
            <code className="font-mono">{entry.action}</code>
          </Fact>
          <Fact label="By">
            {who}
            {entry.actor.type === 'user' && entry.actor.email && entry.actor.name ? ` (${entry.actor.email})` : ''}
          </Fact>
          {entry.ip_address && <Fact label="IP address">{entry.ip_address}</Fact>}
          {entry.request_id && (
            <Fact label="Reference">
              <code className="font-mono break-all">{entry.request_id}</code>
            </Fact>
          )}
          {entry.details && Object.keys(entry.details).length > 0 && (
            <Fact label="Details">
              <pre className="overflow-x-auto font-mono whitespace-pre-wrap break-all">
                {JSON.stringify(entry.details, null, 2)}
              </pre>
            </Fact>
          )}
        </dl>
      </details>
    </li>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}