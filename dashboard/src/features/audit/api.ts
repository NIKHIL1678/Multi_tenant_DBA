// The audit log: newest first, loaded in pages with a cursor ("everything older than X"),
// so new activity never shifts what you have already scrolled through.

import { useInfiniteQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { AuditPage } from '@/lib/types'

export type AuditFilters = {
  /** Action prefix, e.g. "member." for everything about members. */
  area?: string
  /** User id of the person who did it. */
  actorId?: string
  /** How far back: '1d' | '7d' | '30d'. Empty = all time. */
  period?: string
}

const PERIOD_DAYS: Record<string, number> = { '1d': 1, '7d': 7, '30d': 30 }
const PAGE_SIZE = 50

export const auditKeys = {
  list: (tenantId: string, filters: AuditFilters) => ['tenants', tenantId, 'audit', filters] as const,
}

export function useAuditLog(tenantId: string, filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: auditKeys.list(tenantId, filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const q = new URLSearchParams({ limit: String(PAGE_SIZE) })
      if (filters.area) q.set('action', filters.area)
      if (filters.actorId) q.set('actor_id', filters.actorId)
      const days = filters.period ? PERIOD_DAYS[filters.period] : undefined
      if (days) q.set('since', new Date(Date.now() - days * 86_400_000).toISOString())
      if (pageParam) q.set('cursor', pageParam)
      return api<AuditPage>(`/v1/tenants/${tenantId}/audit-log?${q}`, { signal })
    },
    getNextPageParam: (last) => last.next_cursor,
  })
}