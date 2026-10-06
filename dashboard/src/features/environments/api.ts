// Everything the dashboard asks the backend about environments.

import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Environment } from '@/lib/types'

export const environmentKeys = {
  list: (tenantId: string) => ['tenants', tenantId, 'environments'] as const,
}

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