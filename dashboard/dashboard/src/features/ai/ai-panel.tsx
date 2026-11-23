import { Maximize2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { useConversations } from '@/features/ai/api'
import { Chat, type ExplainRequest } from '@/features/ai/chat'
import type { Datasource } from '@/lib/types'

export type { ExplainRequest } from '@/features/ai/chat'

/** Ask AI from a server page: a side panel with this server's conversations. */
export function AiPanel({
  tenantId,
  datasource,
  open,
  onOpenChange,
  explain,
}: {
  tenantId: string
  datasource: Datasource
  open: boolean
  onOpenChange: (open: boolean) => void
  explain: ExplainRequest | null
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" title="Ask AI" className="w-full max-w-full bg-background sm:max-w-xl">
        <Body tenantId={tenantId} datasource={datasource} explain={explain} />
      </SheetContent>
    </Sheet>
  )
}

function Body({
  tenantId,
  datasource: d,
  explain,
}: {
  tenantId: string
  datasource: Datasource
  explain: ExplainRequest | null
}) {
  const conversations = useConversations(tenantId, d.id)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const fullPage = `/t/${tenantId}/ai${conversationId ? `?c=${conversationId}` : `?server=${d.id}`}`

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="grid gap-2 border-b p-4 pr-12">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="size-4 shrink-0 text-primary" aria-hidden />
          <h2 className="text-base font-semibold">Ask AI</h2>
          <span className="truncate font-mono text-sm text-muted-foreground">{d.local_name}</span>
          <Link
            to={fullPage}
            className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            <Maximize2 className="size-3.5" aria-hidden />
            Open in AI Assistant
          </Link>
        </div>
        <NativeSelect
          aria-label="Conversation"
          value={conversationId ?? ''}
          onChange={(e) => setConversationId(e.target.value || null)}
        >
          <option value="">New conversation</option>
          {(conversations.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </NativeSelect>
      </header>
      <Chat
        tenantId={tenantId}
        datasourceId={d.id}
        conversationId={conversationId}
        onConversation={setConversationId}
        explain={explain}
      />
    </div>
  )
}
