import { useQueryClient } from '@tanstack/react-query'
import { Bot, Send } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { aiKeys, isActive, useAiStatus, useConversation, useRun, useStartRun } from '@/features/ai/api'
import { RunView } from '@/features/ai/run-view'
import { describeError } from '@/lib/api'
import type { AgentRun, AgentRunIn } from '@/lib/types'

export type ExplainRequest = { problem: string; title: string; nonce: number }

const MAX_MESSAGE = 2000
const EXAMPLES = [
  'How is this server doing?',
  'Which statements are slowest, and why?',
  'Are there indexes I could remove?',
  'Which tables have no primary key?',
]

/**
 * One conversation with the agents about one server: the thread, live progress and the input.
 * Used by the AI Assistant page and the server page's side panel. `conversationId` null is a new
 * conversation; the first question creates it and `onConversation` reports its id.
 */
export function Chat({
  tenantId,
  datasourceId,
  conversationId,
  onConversation,
  explain = null,
}: {
  tenantId: string
  datasourceId: string | null
  conversationId: string | null
  onConversation: (id: string) => void
  explain?: ExplainRequest | null
}) {
  const queryClient = useQueryClient()
  const status = useAiStatus(tenantId)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const conversation = useConversation(tenantId, conversationId)
  const active = useRun(tenantId, activeRunId)
  const start = useStartRun(tenantId, datasourceId ?? '')
  const handledExplain = useRef<number | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const busy = start.isPending || isActive(active.data)
  const enabled = status.data?.enabled ?? true
  const ready = enabled && datasourceId !== null

  // Another conversation was opened: forget the run that belonged to the previous one. Only a
  // real change counts: a new conversation's id can arrive a render after its first run (the
  // AI Assistant page keeps it in the URL), and that run must keep being followed.
  const activeConversation = active.data?.conversation_id ?? null
  const shownConversation = useRef(conversationId)
  useEffect(() => {
    if (shownConversation.current === conversationId) return
    shownConversation.current = conversationId
    if (activeRunId && activeConversation !== conversationId) setActiveRunId(null)
  }, [conversationId, activeConversation, activeRunId])

  function run(body: AgentRunIn) {
    if (!datasourceId) return
    start.mutate(body, {
      onSuccess: (r) => {
        setActiveRunId(r.id)
        if (r.conversation_id) onConversation(r.conversation_id)
      },
    })
  }

  // Explain: a new conversation about one problem of the server page.
  useEffect(() => {
    if (!explain || handledExplain.current === explain.nonce || !ready) return
    handledExplain.current = explain.nonce
    run({ kind: 'explain', problem: explain.problem, problem_title: explain.title })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per Explain click
  }, [explain, ready])

  // When the active run ends, reload the conversation so its answer and messages are saved ones.
  const activeDone = active.data !== undefined && !isActive(active.data)
  useEffect(() => {
    if (!activeDone || !activeConversation) return
    void queryClient.invalidateQueries({ queryKey: aiKeys.conversation(tenantId, activeConversation) })
    void queryClient.invalidateQueries({ queryKey: aiKeys.all(tenantId), exact: true })
    if (datasourceId) void queryClient.invalidateQueries({ queryKey: aiKeys.conversations(tenantId, datasourceId) })
    void queryClient.invalidateQueries({ queryKey: aiKeys.status(tenantId) })
  }, [activeDone, activeConversation, queryClient, tenantId, datasourceId])

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
    if (!message || busy || !ready) return
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
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!enabled ? (
          <Alert>
            <Bot aria-hidden />
            <AlertTitle>AI is not set up on this server</AlertTitle>
            <AlertDescription>
              An administrator adds a Groq API key (GROQ_API_KEY) to the control plane and restarts it. Everything
              else keeps working without it.
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
                <Button key={q} variant="outline" size="sm" disabled={busy || !ready} onClick={() => send(q)}>
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
            disabled={!ready}
            rows={2}
            placeholder={
              !enabled ? 'AI is not set up' : datasourceId ? 'Ask about this server… (Enter to send)' : 'Pick a server first'
            }
            className="min-h-10 flex-1 resize-none rounded-md border border-input bg-card px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 md:text-sm"
          />
          <Button type="submit" size="icon" aria-label="Send" disabled={!ready || busy || !draft.trim()}>
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
