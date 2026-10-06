// Everything the dashboard asks the backend about environments.

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { memberKeys } from '@/features/members/api'
import { tenantKeys } from '@/features/tenants/api'
import { api } from '@/lib/api'
import type { Environment } from '@/lib/types'

export const environmentKeys = {
  list: (tenantId: string) => ['tenants', tenantId, 'environments'] as const,
}

/** Lowercase letters, digits, '-' or '_', starting with a letter or digit. Same rule as the backend. */
export const ENV_NAME_PATTERN = /^[a-z0-9][a-z0-9_-]{0,59}$/

/** Production first, then by name. */
function sortEnvironments(envs: Environment[]): Environment[] {
  return [...envs].sort((a, b) => Number(b.is_production) - Number(a.is_production) || a.name.localeCompare(b.name))
}

export function useEnvironments(tenantId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: environmentKeys.list(tenantId),
    queryFn: () => api<Environment[]>(`/v1/tenants/${tenantId}/environments`),
    select: sortEnvironments,
    enabled,
  })
}

/** Other screens show environment names and counts: refresh them after any change. */
function refreshRelated(queryClient: QueryClient, tenantId: string) {
  void queryClient.invalidateQueries({ queryKey: tenantKeys.overview(tenantId) })
  void queryClient.invalidateQueries({ queryKey: memberKeys.list(tenantId) })
}

export function useCreateEnvironment(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; is_production: boolean }) =>
      api<Environment>(`/v1/tenants/${tenantId}/environments`, { method: 'POST', body }),
    onSuccess: (env) => {
      queryClient.setQueryData<Environment[]>(environmentKeys.list(tenantId), (list) => list && [...list, env])
      refreshRelated(queryClient, tenantId)
    },
  })
}

export function useUpdateEnvironment(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; is_production?: boolean }) =>
      api<Environment>(`/v1/tenants/${tenantId}/environments/${id}`, { method: 'PATCH', body }),
    onSuccess: (env) => {
      queryClient.setQueryData<Environment[]>(environmentKeys.list(tenantId), (list) =>
        list?.map((e) => (e.id === env.id ? env : e)),
      )
      refreshRelated(queryClient, tenantId)
    },
  })
}

export function useDeleteEnvironment(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/v1/tenants/${tenantId}/environments/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Environment[]>(environmentKeys.list(tenantId), (list) => list?.filter((e) => e.id !== id))
      refreshRelated(queryClient, tenantId)
    },
  })
}