// Ask AI and Explain: start a run, follow its progress, read conversations.
// A run takes a few seconds; while it is queued or running its progress is polled every second.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { AgentRun, AgentRunIn, AiConversation, AiConversationDetail, AiStatus } from '@/lib/types'

export const aiKeys = {
  status: (tenantId: string) => ['tenants', tenantId, 'ai', 'status'] as const,
  run: (tenantId: string, id: string) => ['tenants', tenantId, 'ai', 'runs', id] as const,
  conversations: (tenantId: string, datasourceId: string) =>
    ['tenants', tenantId, 'datasources', datasourceId, 'ai', 'conversations'] as const,
  conversation: (tenantId: string, id: string) => ['tenants', tenantId, 'ai', 'conversations', id] as const,
}

export function isActive(run: Pick<AgentRun, 'status'> | undefined): boolean {
  return run?.status === 'queued' || run?.status === 'running'
}

/** Is AI set up on the server, and how much of today's allowance is used. */
export function useAiStatus(tenantId: string) {
  return useQuery({
    queryKey: aiKeys.status(tenantId),
    queryFn: () => api<AiStatus>(`/v1/tenants/${tenantId}/ai/status`),
    staleTime: 30_000,
  })
}

export function useStartRun(tenantId: string, datasourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AgentRunIn) =>
      api<AgentRun>(`/v1/tenants/${tenantId}/datasources/${datasourceId}/ai/runs`, { method: 'POST', body }),
    onSuccess: (run) => {
      queryClient.setQueryData(aiKeys.run(tenantId, run.id), run)
      void queryClient.invalidateQueries({ queryKey: aiKeys.status(tenantId) })
      void queryClient.invalidateQueries({ queryKey: aiKeys.conversations(tenantId, datasourceId) })
      if (run.conversation_id)
        void queryClient.invalidateQueries({ queryKey: aiKeys.conversation(tenantId, run.conversation_id) })
    },
  })
}

/** One run; polled every second until it is done, needs input or failed. */
export function useRun(tenantId: string, id: string | null) {
  return useQuery({
    queryKey: aiKeys.run(tenantId, id ?? ''),
    queryFn: () => api<AgentRun>(`/v1/tenants/${tenantId}/ai/runs/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (isActive(query.state.data) ? 1000 : false),
  })
}

export function useConversations(tenantId: string, datasourceId: string) {
  return useQuery({
    queryKey: aiKeys.conversations(tenantId, datasourceId),
    queryFn: () => api<AiConversation[]>(`/v1/tenants/${tenantId}/datasources/${datasourceId}/ai/conversations`),
  })
}

export function useConversation(tenantId: string, id: string | null) {
  return useQuery({
    queryKey: aiKeys.conversation(tenantId, id ?? ''),
    queryFn: () => api<AiConversationDetail>(`/v1/tenants/${tenantId}/ai/conversations/${id}`),
    enabled: id !== null,
  })
}
