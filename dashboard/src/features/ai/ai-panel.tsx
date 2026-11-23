import { useQueryClient } from '@tanstack/react-query'
import { Bot, Send, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  aiKeys,
  isActive,
  useAiStatus,
  useConversation,
  useConversations,
  useRun,
  useStartRun,
} from '@/features/ai/api'
import { RunView } from '@/features/ai/run-view'
import { describeError } from '@/lib/api'
import type { AgentRun, AgentRunIn, Datasource } from '@/lib/types'

export type ExplainRequest = { problem: string; title: string; nonce: number }

const MAX_MESSAGE = 2000
const EXAMPLES = [
  'How is this server doing?',
  'Which statements are slowest, and why?',
  'Are there indexes I could remove?',
  'Which tables have no primary key?',
]

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
  const queryClient = useQueryClient()
  const status = useAiStatus(tenantId)
  const conversations = useConversations(tenantId, d.id)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const conversation = useConversation(tenantId, conversationId)
  const active = useRun(tenantId, activeRunId)
  const start = useStartRun(tenantId, d.id)
  const handledExplain = useRef<number | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const busy = start.isPending || isActive(active.data)
  const enabled = status.data?.enabled ?? true

  function run(body: AgentRunIn) {
    start.mutate(body, {
      onSuccess: (r) => {
        setActiveRunId(r.id)
        setConversationId(r.conversation_id)
      },
    })
  }

  // Explain: a new conversation about one problem of the server page.
  useEffect(() => {
    if (!explain || handledExplain.current === explain.nonce || !enabled) return
    handledExplain.current = explain.nonce
    run({ kind: 'explain', problem: explain.problem, problem_title: explain.title })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per Explain click
  }, [explain, enabled])

  // When the active run ends, reload the conversation so its answer and messages are saved ones.
  const activeDone = active.data !== undefined && !isActive(active.data)
  useEffect(() => {
    if (!activeDone || !active.data?.conversation_id) return
    void queryClient.invalidateQueries({ queryKey: aiKeys.conversation(tenantId, active.data.conversation_id) })
    void queryClient.invalidateQueries({ queryKey: aiKeys.conversations(tenantId, d.id) })
    void queryClient.invalidateQueries({ queryKey: aiKeys.status(tenantId) })
  }, [activeDone, active.data?.conversation_id, queryClient, tenantId, d.id])

  // The thread: every run of the conversation, the active one replaced by its live progress.
  const thread = useMemo(() => {
    const runs: AgentRun[] = [...(conversation.data?.runs ?? [])]
    const live = active.data
    if (live && live.conversation_id === conversationId) {
      const i = runs.findIndex((r) => r.id === live.id)
      if (i >= 0) runs[i] = live
      else runs.push(live)
    }
    const asked = new Map<string, string>()
    for (const m of conversation.data?.messages ?? []) if (m.role === 'user' && m.run_id) asked.set(m.run_id, m.content)
    return runs.map((r) => ({ run: r, asked: asked.get(r.id) ?? r.question }))
  }, [conversation.data, active.data, conversationId])

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [thread.length, active.data?.steps.length, active.data?.status])

  function send(text: string) {
    const message = text.trim()
    if (!message || busy) return
    run({ kind: 'chat', message, conversation_id: conversationId ?? undefined })
    setDraft('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send(draft)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="grid gap-2 border-b p-4 pr-12">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="size-4 shrink-0 text-primary" aria-hidden />
          <h2 className="text-base font-semibold">Ask AI</h2>
          <span className="truncate font-mono text-sm text-muted-foreground">{d.local_name}</span>
        </div>
        <NativeSelect
          aria-label="Conversation"
          value={conversationId ?? ''}
          onChange={(e) => {
            setConversationId(e.target.value || null)
            setActiveRunId(null)
            start.reset()
          }}
        >
          <option value="">New conversation</option>
          {(conversations.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </NativeSelect>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!enabled ? (
          <Alert>
            <Bot aria-hidden />
            <AlertTitle>AI is not set up on this server</AlertTitle>
            <AlertDescription>
              An administrator adds a Groq API key (GROQ_API_KEY) to the control plane. Everything else keeps
              working without it.
            </AlertDescription>
          </Alert>
        ) : conversationId !== null && conversation.isPending && !active.data ? (
          <div className="grid gap-3" aria-busy aria-label="Loading the conversation">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : thread.length === 0 ? (
          <div className="grid gap-3">
            <p className="text-sm text-muted-foreground">
              Ask about this server's health, slow statements, tables or indexes. The agents read its statistics,
              never the rows inside tables.
            </p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((q) => (
                <Button key={q} variant="outline" size="sm" disabled={busy} onClick={() => send(q)}>
                  {q}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="grid gap-5">
            {thread.map(({ run: r, asked }) => (
              <li key={r.id} className="grid gap-3">
                <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm whitespace-pre-line text-primary-foreground">
                  {asked}
                </p>
                <div className="flex gap-2">
                  <Bot className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <RunView
                      run={r}
                      busy={busy}
                      onFollowUp={send}
                      onChooseTable={(table) =>
                        run({ kind: 'chat', table, conversation_id: r.conversation_id ?? undefined })
                      }
                      onRetry={() => send(r.question)}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
        {start.isError && (
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>Could not ask</AlertTitle>
            <AlertDescription>{describeError(start.error)}</AlertDescription>
          </Alert>
        )}
        <div ref={bottom} />
      </div>

      <form
        className="grid gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Your question"
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, MAX_MESSAGE))}
            onKeyDown={onKeyDown}
            disabled={!enabled}
            rows={2}
            placeholder={enabled ? 'Ask about this server… (Enter to send)' : 'AI is not set up'}
            className="min-h-10 flex-1 resize-none rounded-md border border-input bg-card px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 md:text-sm"
          />
          <Button type="submit" size="icon" aria-label="Send" disabled={!enabled || busy || !draft.trim()}>
            <Send />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          AI can be wrong. Every claim cites evidence and suggested SQL is checked, but read it before running it.
          {status.data && ` ${status.data.runs_today} of ${status.data.runs_limit} questions used today.`}
        </p>
      </form>
    </div>
  )
}
