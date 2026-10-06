// Everything the dashboard asks the backend about connectors.

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { tenantKeys } from '@/features/tenants/api'
import { api } from '@/lib/api'
import type { Connector, ConnectorCreated, Enrollment } from '@/lib/types'

export const connectorKeys = {
  list: (tenantId: string) => ['tenants', tenantId, 'connectors'] as const,
  detail: (tenantId: string, id: string) => ['tenants', tenantId, 'connectors', id] as const,
}

const STATUS_ORDER: Record<string, number> = { online: 0, offline: 1, pending: 2, revoked: 3 }

/** Working connectors first, revoked last; then by name. */
function sortConnectors(list: Connector[]): Connector[] {
  return [...list].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || a.name.localeCompare(b.name),
  )
}

export function useConnectors(tenantId: string) {
  return useQuery({
    queryKey: connectorKeys.list(tenantId),
    queryFn: () => api<Connector[]>(`/v1/tenants/${tenantId}/connectors`),
    select: sortConnectors,
    refetchInterval: 30_000, // status changes on its own (online/offline): keep it fresh
  })
}

/** One connector. `watch` checks every few seconds, e.g. while waiting for it to be installed. */
export function useConnector(tenantId: string, id: string, { watch = false }: { watch?: boolean } = {}) {
  return useQuery({
    queryKey: connectorKeys.detail(tenantId, id),
    queryFn: () => api<Connector>(`/v1/tenants/${tenantId}/connectors/${id}`),
    refetchInterval: watch ? 4_000 : false,
  })
}

function store(queryClient: QueryClient, tenantId: string, connector: Connector) {
  queryClient.setQueryData(connectorKeys.detail(tenantId, connector.id), connector)
  queryClient.setQueryData<Connector[]>(connectorKeys.list(tenantId), (list) => {
    if (!list) return list
    return list.some((c) => c.id === connector.id)
      ? list.map((c) => (c.id === connector.id ? connector : c))
      : [...list, connector]
  })
  void queryClient.invalidateQueries({ queryKey: tenantKeys.overview(tenantId) })
}

export function useCreateConnector(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<ConnectorCreated>(`/v1/tenants/${tenantId}/connectors`, { method: 'POST', body: { name } }),
    onSuccess: (created) => store(queryClient, tenantId, created.connector),
  })
}

/** A fresh install command for a connector that is still waiting. Older commands stop working. */
export function useNewEnrollmentToken(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<Enrollment>(`/v1/tenants/${tenantId}/connectors/${id}/enrollment-token`, { method: 'POST' }),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: connectorKeys.detail(tenantId, id) })
      void queryClient.invalidateQueries({ queryKey: connectorKeys.list(tenantId), exact: true })
    },
  })
}

export function useRenameConnector(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api<Connector>(`/v1/tenants/${tenantId}/connectors/${id}`, { method: 'PATCH', body: { name } }),
    onSuccess: (connector) => store(queryClient, tenantId, connector),
  })
}

export function useRevokeConnector(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<Connector>(`/v1/tenants/${tenantId}/connectors/${id}/revoke`, { method: 'POST' }),
    onSuccess: (connector) => store(queryClient, tenantId, connector),
  })
}