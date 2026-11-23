// "Needs attention" on a server's overview: plain rules over the latest collected statistics.
// Phase 5 adds the AI's findings next to these; these stay as the always-on baseline.

import { formatBytes, formatCount, formatDate, formatMs, formatPercent, formatWait } from '@/lib/format'
import type { QueryStat, ServerSnapshots } from '@/lib/types'

export type ServerTab = 'overview' | 'databases' | 'tables' | 'indexes' | 'queries'

export type AttentionItem = {
  id: string
  level: 'warning' | 'info'
  title: string
  detail?: string
  tab?: ServerTab
}

const SLOW_MS = 100 // average time that makes a statement without an index worth fixing
const MANY_ROWS = 10_000 // rows read per run that make a statement without an index worth fixing
const VERY_SLOW_MS = 1000

/** Rows the server read per run (MySQL); many rows for few returned means a missing index. */
export function rowsReadPerRun(q: QueryStat): number | null {
  return q.rows_examined != null && q.calls > 0 ? Math.round(q.rows_examined / q.calls) : null
}

/** Ran without an index AND it costs something: slow on average or reads many rows each run. */
export function needsIndex(q: QueryStat): boolean {
  return (q.no_index_used ?? 0) > 0 && (q.mean_ms >= SLOW_MS || (rowsReadPerRun(q) ?? 0) >= MANY_ROWS)
}

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`
const qualified = (x: { schema: string; table: string }) => `${x.schema}.${x.table}`

/** Most important first: warnings, then information. */
export function attentionItems(s: ServerSnapshots | undefined): AttentionItem[] {
  if (!s) return []
  const items: AttentionItem[] = []
  const h = s.health?.data
  const ix = s.indexes?.data
  const tables = s.table_stats?.data.tables ?? []
  const locks = s.locks?.data.available ? s.locks.data : undefined
  const slow = s.slow_queries?.data.available ? s.slow_queries.data : undefined

  if (locks?.waits.length) {
    const longest = Math.max(...locks.waits.map((w) => w.wait_seconds ?? 0))
    const top = locks.waits.find((w) => (w.wait_seconds ?? 0) === longest) ?? locks.waits[0]
    items.push({
      id: 'lockwaits',
      level: 'warning',
      title: `${plural(locks.waits.length, 'session was', 'sessions were')} waiting for a lock`,
      detail:
        top.schema && top.table
          ? `Longest: ${formatWait(longest)} on ${top.schema}.${top.table}. Another session holds the rows.`
          : `Longest: ${formatWait(longest)}. Another session holds the rows.`,
      tab: 'queries',
    })
  }
  if (slow) {
    const noIndex = slow.queries.filter(needsIndex)
    if (noIndex.length) {
      const worst = noIndex.reduce((a, b) => (b.total_ms > a.total_ms ? b : a))
      items.push({
        id: 'noindex',
        level: 'warning',
        title: `${plural(noIndex.length, 'statement runs', 'statements run')} without a needed index`,
        detail: `Costliest: ${formatMs(worst.total_ms)} in total over ${formatCount(worst.calls)} runs.`,
        tab: 'queries',
      })
    } else {
      const slowest = slow.queries.filter((q) => q.mean_ms >= VERY_SLOW_MS)
      if (slowest.length)
        items.push({
          id: 'slowest',
          level: 'info',
          title: `${plural(slowest.length, 'statement takes', 'statements take')} over ${formatMs(VERY_SLOW_MS)} on average`,
          tab: 'queries',
        })
    }
  }
  if (locks?.long_transactions.length)
    items.push({
      id: 'longtrx',
      level: 'info',
      title: `${plural(locks.long_transactions.length, 'transaction is', 'transactions are')} open for over ${formatWait(locks.long_transaction_seconds)}`,
      detail: 'Open transactions can hold locks and stop cleanup. Often an app forgot to commit.',
      tab: 'queries',
    })

  if (h) {
    const { current, max } = h.connections
    if (current != null && max) {
      const used = current / max
      if (used >= 0.8)
        items.push({
          id: 'connections',
          level: 'warning',
          title: `Connections are at ${formatPercent(used)} of the limit`,
          detail: `${current} of ${max}. New connections are refused once the limit is reached.`,
        })
    }
    if (h.cache_hit_ratio != null && h.cache_hit_ratio < 0.95)
      items.push({
        id: 'cache',
        level: 'warning',
        title: `Cache hit rate is ${formatPercent(h.cache_hit_ratio)}`,
        detail: 'The server often reads from disk instead of memory. A bigger buffer or better indexes help.',
      })
    const lag = h.replication.lag_seconds
    if (h.replication.is_replica && lag != null && lag > 60)
      items.push({
        id: 'lag',
        level: 'warning',
        title: `This replica is ${Math.round(lag)} seconds behind`,
        detail: 'Reads from it may return old data.',
      })
    if (h.deadlocks)
      items.push({
        id: 'deadlocks',
        level: 'info',
        title: `${plural(h.deadlocks, 'deadlock')} since the server started`,
      })
    if (h.settings.slow_query_log === 'OFF')
      items.push({
        id: 'slowlog',
        level: 'info',
        title: 'The slow query log is off',
        detail: 'Slow queries are still found through performance_schema; the log adds detail.',
        tab: 'queries',
      })
    if (h.settings.log_min_duration_statement === '-1')
      items.push({ id: 'pglog', level: 'info', title: 'Slow statements are not logged' })
  }

  if (ix) {
    const since = ix.usage_since ? ` since ${formatDate(ix.usage_since)}` : ''
    if (ix.invalid.length)
      items.push({
        id: 'invalid',
        level: 'warning',
        title: `${plural(ix.invalid.length, 'index is', 'indexes are')} broken`,
        detail: 'Left by a failed index build. They slow writes and are never used.',
        tab: 'indexes',
      })
    if (ix.full_scans.length) {
      const top = ix.full_scans[0]
      items.push({
        id: 'fullscans',
        level: 'warning',
        title: `${plural(ix.full_scans.length, 'big table is', 'big tables are')} often read in full`,
        detail: `Biggest: ${qualified(top)}. A missing index is the usual cause.`,
        tab: 'indexes',
      })
    }
    if (ix.unindexed_foreign_keys.length)
      items.push({
        id: 'fk',
        level: 'warning',
        title: `${plural(ix.unindexed_foreign_keys.length, 'foreign key has', 'foreign keys have')} no index`,
        detail: 'Joins and deletes on the parent table scan the whole child table.',
        tab: 'indexes',
      })
    if (ix.missing_primary_keys.length)
      items.push({
        id: 'pk',
        level: 'warning',
        title: `${plural(ix.missing_primary_keys.length, 'table has', 'tables have')} no primary key`,
        detail: 'Rows cannot be told apart reliably; replication and updates suffer.',
        tab: 'indexes',
      })
    if (ix.duplicates.length)
      items.push({
        id: 'dupes',
        level: 'warning',
        title: `${plural(ix.duplicates.length, 'index is', 'indexes are')} duplicated by another`,
        detail: 'They use disk and slow every write without making reads faster.',
        tab: 'indexes',
      })
    if (ix.unused.length)
      items.push({
        id: 'unused',
        level: 'info',
        title: `${plural(ix.unused.length, 'index has', 'indexes have')} not been used${since}`,
        detail: 'Check over a longer period before removing any.',
        tab: 'indexes',
      })
  }

  const reclaim = tables.filter(
    (t) => t.free_bytes != null && t.data_bytes && t.free_bytes > 100 * 1024 ** 2 && t.free_bytes > t.data_bytes * 0.3,
  )
  if (reclaim.length) {
    const total = reclaim.reduce((sum, t) => sum + (t.free_bytes ?? 0), 0)
    items.push({
      id: 'reclaim',
      level: 'info',
      title: `${formatBytes(total)} of free space could be reclaimed`,
      detail: `In ${plural(reclaim.length, 'table')}, after many deletes.`,
      tab: 'tables',
    })
  }
  const bloated = tables.filter((t) => t.dead_rows != null && t.rows && t.dead_rows > 10_000 && t.dead_rows > t.rows * 0.2)
  if (bloated.length)
    items.push({
      id: 'dead',
      level: 'info',
      title: `${plural(bloated.length, 'table has', 'tables have')} many dead rows`,
      detail: 'VACUUM has not caught up after updates and deletes.',
      tab: 'tables',
    })

  return items.sort((a, b) => Number(a.level === 'info') - Number(b.level === 'info'))
}
