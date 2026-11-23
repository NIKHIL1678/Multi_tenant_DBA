import { Database, ExternalLink, MessageSquare, Plus, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { QueryError } from '@/components/query-error'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { useAllConversations } from '@/features/ai/api'
import { Chat } from '@/features/ai/chat'
import { useDatasources } from '@/features/datasources/api'
import { EngineBadge, EnvironmentTag } from '@/features/datasources/datasource-badges'
import { formatRelative } from '@/lib/format'
import { useTenant } from '@/lib/tenant-context'
import type { AiConversationItem, Datasource } from '@/lib/types'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

const SUPPORTED = new Set(['postgres', 'mysql', 'mariadb'])

// The last server asked about, per company: a convenience only (never anything sensitive).
const lastServerKey = (tenantId: string) => `zipzy-dba.ai.server.${tenantId}`

function readLastServer(tenantId: string): string | null {
  try {
    return localStorage.getItem(lastServerKey(tenantId))
  } catch {
    return null
  }
}

function rememberServer(tenantId: string, id: string) {
  try {
    localStorage.setItem(lastServerKey(tenantId), id)
  } catch {
    // Storage blocked (private window): the picker simply starts empty next time.
  }
}

/** AI Assistant: chat with the agents about any server, without opening it first. */
export function AiPage() {
  const { tenant } = useTenant()
  const now = useNow()
  const [params, setParams] = useSearchParams()
  const conversations = useAllConversations(tenant.id)
  const datasources = useDatasources(tenant.id)
  const servers = useMemo(() => (datasources.data ?? []).filter((d) => SUPPORTED.has(d.engine)), [datasources.data])

  const conversationId = params.get('c')
  const current = conversations.data?.find((c) => c.id === conversationId)
  const [choice, setPicked] = useState<string | null>(() => params.get('server') ?? readLastServer(tenant.id))
  // A remembered server that is gone (or no longer visible) does not count; with one server, it is it.
  const picked =
    choice && servers.some((s) => s.id === choice) ? choice : servers.length === 1 ? servers[0].id : null

  const serverId = current?.datasource_id ?? picked
  const server = servers.find((s) => s.id === serverId) ?? null

  function open(id: string | null) {
    setParams(
      (p) => {
        if (id) p.set('c', id)
        else p.delete('c')
        p.delete('server')
        return p
      },
      { replace: false },
    )
  }

  function pick(id: string) {
    setPicked(id)
    rememberServer(tenant.id, id)
  }

  if (datasources.isError) return <QueryError error={datasources.error} />

  return (
    <>
      <PageHeader
        title="AI Assistant"
        description="Ask the agents about any of your servers. They read statistics and structure, never the rows in your tables."
      />

      {datasources.isPending ? (
        <Skeleton className="h-96" />
      ) : servers.length === 0 ? (
        <EmptyState
          icon={Database}
          title="No server to ask about yet"
          description="Connect a MySQL or PostgreSQL server first; then ask the agents about it here."
          action={
            <Button asChild>
              <Link to={`/t/${tenant.id}/connectors`}>Go to Connectors</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-[17rem_minmax(0,1fr)]">
          <Card className="hidden min-h-0 flex-col overflow-hidden md:flex md:h-[calc(100dvh-11rem)]">
            <div className="border-b p-3">
              <Button className="w-full" variant={conversationId ? 'outline' : 'default'} onClick={() => open(null)}>
                <Plus />
                New chat
              </Button>
            </div>
            <ConversationList
              items={conversations.data}
              loading={conversations.isPending}
              activeId={conversationId}
              onOpen={open}
              now={now}
            />
          </Card>

          <Card className="flex h-[calc(100dvh-11rem)] min-h-[30rem] flex-col overflow-hidden">
            <header className="grid gap-2 border-b p-3">
              {/* Phones: the conversation list is a picker here. */}
              <NativeSelect
                className="md:hidden"
                aria-label="Conversation"
                value={conversationId ?? ''}
                onChange={(e) => open(e.target.value || null)}
              >
                <option value="">New chat</option>
                {(conversations.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title} · {c.datasource_name}
                  </option>
                ))}
              </NativeSelect>

              {conversationId ? (
                <ServerLine tenantId={tenant.id} server={server} fallbackName={current?.datasource_name} />
              ) : (
                <label className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
                  <span className="shrink-0 text-sm font-medium">Ask about</span>
                  <NativeSelect
                    className="flex-1"
                    aria-label="Server"
                    value={picked ?? ''}
                    onChange={(e) => e.target.value && pick(e.target.value)}
                  >
                    <option value="" disabled>
                      Choose a server…
                    </option>
                    {servers.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.local_name} · {s.environment.name}
                        {s.connector.status === 'online' ? '' : ' (connector offline)'}
                      </option>
                    ))}
                  </NativeSelect>
                </label>
              )}
            </header>

            <Chat
              tenantId={tenant.id}
              datasourceId={serverId}
              conversationId={conversationId}
              onConversation={(id) => open(id)}
            />
          </Card>
        </div>
      )}
    </>
  )
}

function ServerLine({
  tenantId,
  server,
  fallbackName,
}: {
  tenantId: string
  server: Datasource | null
  fallbackName?: string
}) {
  if (!server)
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Database className="size-4" aria-hidden />
        <span className="font-mono">{fallbackName ?? 'Server'}</span>
      </p>
    )
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="truncate font-mono text-sm font-medium">{server.local_name}</span>
      <EngineBadge engine={server.engine} version={server.version} />
      <EnvironmentTag name={server.environment.name} production={server.environment.is_production} />
      <Link
        to={`/t/${tenantId}/databases/${server.id}`}
        className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        Open server
        <ExternalLink className="size-3.5" aria-hidden />
      </Link>
    </div>
  )
}

function ConversationList({
  items,
  loading,
  activeId,
  onOpen,
  now,
}: {
  items: AiConversationItem[] | undefined
  loading: boolean
  activeId: string | null
  onOpen: (id: string) => void
  now: number
}) {
  if (loading)
    return (
      <div className="grid gap-2 p-3">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    )
  if (!items?.length)
    return (
      <p className="flex items-start gap-2 p-4 text-sm text-muted-foreground">
        <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden />
        Your conversations appear here.
      </p>
    )
  return (
    <ul className="min-h-0 flex-1 overflow-y-auto p-2" aria-label="Conversations">
      {items.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onOpen(c.id)}
            aria-current={c.id === activeId ? 'true' : undefined}
            className={cn(
              'grid w-full gap-0.5 rounded-md px-3 py-2 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
              c.id === activeId && 'bg-accent text-accent-foreground',
            )}
          >
            <span className="flex items-center gap-1.5 text-sm">
              <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{c.title}</span>
            </span>
            <span className="flex min-w-0 items-center gap-1.5 pl-5 text-xs text-muted-foreground">
              <span className="truncate font-mono">{c.datasource_name}</span>
              <span aria-hidden>·</span>
              <span className="shrink-0">{formatRelative(c.updated_at, now)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
