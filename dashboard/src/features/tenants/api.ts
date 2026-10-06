// Everything the dashboard asks the backend about companies. Pages use these hooks and never
// call fetch themselves, so caching, loading states and refreshing live in one place.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Tenant, TenantOverview } from '@/lib/types'

export const tenantKeys = {
  detail: (id: string) => ['tenants', id] as const,
  overview: (id: string) => ['tenants', id, 'overview'] as const,
}

export function useTenantQuery(tenantId: string) {
  return useQuery({
    queryKey: tenantKeys.detail(tenantId),
    queryFn: () => api<Tenant>(`/v1/tenants/${tenantId}`),
  })
}

export function useTenantOverview(tenantId: string) {
  return useQuery({
    queryKey: tenantKeys.overview(tenantId),
    queryFn: () => api<TenantOverview>(`/v1/tenants/${tenantId}/overview`),
  })
}

export function useCreateTenant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api<Tenant>('/v1/tenants', { method: 'POST', body: { name } }),
    onSuccess: (tenant) => queryClient.setQueryData(tenantKeys.detail(tenant.id), tenant),
  })
}