// Everything the dashboard asks the backend about databases (the API calls them datasources).
// Databases are not created here: connectors report them. Here you can move or remove them.

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { connectorKeys } from '@/features/connectors/api'
import { environmentKeys } from '@/features/environments/api'
import { tenantKeys } from '@/features/tenants/api'
import { api } from '@/lib/api'
import type { Datasource, DatasourceCatalog } from '@/lib/types'

export const datasourceKeys = {
  list: (tenantId: string) => ['tenants', tenantId, 'datasources'] as const,
  databases: (tenantId: string, id: string) => ['tenants', tenantId, 'datasources', id, 'databases'] as const,
}

/** Production first, then environment name, then database name. */
function sortDatasources(list: Datasource[]): Datasource[] {
  return [...list].sort(
    (a, b) =>
      Number(b.environment.is_production) - Number(a.environment.is_production) ||
      a.environment.name.localeCompare(b.environment.name) ||
      a.local_name.localeCompare(b.local_name),
  )
}

/** Every database you may see (the server hides environments you have no access to). */
export function useDatasources(tenantId: string) {
  return useQuery({
    queryKey: datasourceKeys.list(tenantId),
    queryFn: () => api<Datasource[]>(`/v1/tenants/${tenantId}/datasources`),
    select: sortDatasources,
    refetchInterval: 60_000, // connectors update status on their own
  })
}

/** Environment and connector pages show database counts: refresh them after a change. */
function refreshCounts(queryClient: QueryClient, tenantId: string) {
  void queryClient.invalidateQueries({ queryKey: environmentKeys.list(tenantId) })
  void queryClient.invalidateQueries({ queryKey: connectorKeys.list(tenantId), exact: true })
  void queryClient.invalidateQueries({ queryKey: tenantKeys.overview(tenantId) })
}

export function useMoveDatasource(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, environmentId }: { id: string; environmentId: string }) =>
      api<Datasource>(`/v1/tenants/${tenantId}/datasources/${id}`, {
        method: 'PATCH',
        body: { environment_id: environmentId },
      }),
    onSuccess: (ds) => {
      queryClient.setQueryData<Datasource[]>(datasourceKeys.list(tenantId), (list) =>
        list?.map((d) => (d.id === ds.id ? ds : d)),
      )
      refreshCounts(queryClient, tenantId)
    },
  })
}

export function useDeleteDatasource(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/v1/tenants/${tenantId}/datasources/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Datasource[]>(datasourceKeys.list(tenantId), (list) => list?.filter((d) => d.id !== id))
      refreshCounts(queryClient, tenantId)
    },
  })
}

/** Every database on one server (MySQL schemas, Postgres databases): names and sizes only. */
export function useServerDatabases(tenantId: string, datasourceId: string | null) {
  return useQuery({
    queryKey: datasourceKeys.databases(tenantId, datasourceId ?? ''),
    queryFn: () => api<DatasourceCatalog>(`/v1/tenants/${tenantId}/datasources/${datasourceId}/databases`),
    enabled: datasourceId !== null,
  })
}

/** Ask the connector to test the server now; this also refreshes its list of databases. */
export function useCheckDatasource(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<Datasource>(`/v1/tenants/${tenantId}/datasources/${id}/check`, { method: 'POST' }),
    onSuccess: (ds) => {
      queryClient.setQueryData<Datasource[]>(datasourceKeys.list(tenantId), (list) =>
        list?.map((d) => (d.id === ds.id ? ds : d)),
      )
      void queryClient.invalidateQueries({ queryKey: datasourceKeys.databases(tenantId, ds.id) })
    },
  })
}
