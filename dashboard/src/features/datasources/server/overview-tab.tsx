import { AlertTriangle, ArrowRight, CheckCircle2, Info, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { attentionItems, type AttentionItem, type ServerTab } from '@/features/datasources/server/attention'
import { Metric, QualifiedName } from '@/features/datasources/server/parts'
import { formatBytes, formatCompact, formatDuration, formatPercent } from '@/lib/format'
import type { Datasource, ServerSnapshots } from '@/lib/types'

export function OverviewTab({
  datasource: d,
  snapshots: s,
  onTab,
  onExplain,
}: {
  datasource: Datasource
  snapshots: ServerSnapshots
  onTab: (tab: ServerTab) => void
  /** Ask the AI agents to explain one problem (not offered when AI cannot look at this engine). */
  onExplain?: (item: AttentionItem) => void
}) {
  const h = s.health?.data
  const items = attentionItems(s)
  const tables = s.table_stats?.data.tables ?? []
  const biggest = tables.slice(0, 5)
  const used = h?.connections.current != null && h.connections.max ? h.connections.current / h.connections.max : null

  return (
    <div className="grid gap-5">
      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <Metric
          label="Connections"
          value={h?.connections.current != null ? `${h.connections.current} / ${h.connections.max ?? '?'}` : null}
          detail={h?.connections.active != null ? `${h.connections.active} running now` : undefined}
          tone={used != null && used >= 0.8 ? 'warning' : undefined}
        />
        <Metric
          label="Cache hit rate"
          value={h?.cache_hit_ratio != null ? formatPercent(h.cache_hit_ratio) : null}
          detail="Reads served from memory"
          tone={h?.cache_hit_ratio != null && h.cache_hit_ratio < 0.95 ? 'warning' : undefined}
        />
        <Metric
          label={h?.throughput_unit === 'transactions' ? 'Transactions / s' : 'Queries / s'}
          value={h?.throughput_per_second != null ? formatCompact(h.throughput_per_second) : null}
          detail="Average since start"
        />
        <Metric
          label="Size"
          value={d.catalog?.total_size_bytes != null ? formatBytes(d.catalog.total_size_bytes) : null}
          detail={
            h?.uptime_seconds != null
              ? `Up ${formatDuration(h.uptime_seconds)}`
              : d.catalog
                ? `${d.catalog.database_count} databases`
                : undefined
          }
        />
      </div>

      {h?.replication.is_replica && (
        <p className="text-sm text-muted-foreground">
          This server is a replica
          {h.replication.lag_seconds != null && `, ${Math.round(h.replication.lag_seconds)} s behind its primary`}.
        </p>
      )}

      <Card className="overflow-hidden">
        <h2 className="border-b px-4 py-3 text-sm font-medium">Needs attention</h2>
        {items.length === 0 ? (
          <p className="flex items-center gap-2 px-4 py-4 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4 text-success" aria-hidden />
            {s.health || s.indexes ? 'Nothing found. Checks run again whenever you collect.' : 'Collect to check this server.'}
          </p>
        ) : (
          <ul className="divide-y">
            {items.map((item) => {
              const Icon = item.level === 'warning' ? AlertTriangle : Info
              return (
                <li key={item.id} className="flex items-start gap-3 px-4 py-3">
                  <Icon
                    className={item.level === 'warning' ? 'mt-0.5 size-4 shrink-0 text-warning' : 'mt-0.5 size-4 shrink-0 text-muted-foreground'}
                    aria-label={item.level === 'warning' ? 'Warning' : 'Note'}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{item.title}</p>
                    {item.detail && <p className="mt-0.5 text-sm text-muted-foreground">{item.detail}</p>}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row">
                    {onExplain && (
                      <Button variant="ghost" size="sm" onClick={() => onExplain(item)} aria-label={`Explain: ${item.title}`}>
                        <Sparkles />
                        Explain
                      </Button>
                    )}
                    {item.tab && (
                      <Button variant="ghost" size="sm" onClick={() => onTab(item.tab!)}>
                        View
                        <ArrowRight />
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      {biggest.length > 0 && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b px-4 py-2">
            <h2 className="text-sm font-medium">Largest tables</h2>
            <Button variant="ghost" size="sm" onClick={() => onTab('tables')}>
              All tables
              <ArrowRight />
            </Button>
          </div>
          <ul className="divide-y">
            {biggest.map((t) => (
              <li key={`${t.schema}.${t.name}`} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="min-w-0 flex-1 truncate font-mono">
                  <QualifiedName schema={t.schema} name={t.name} />
                </span>
                <span className="shrink-0 text-muted-foreground tabular-nums">
                  {t.rows != null && `${formatCompact(t.rows)} rows · `}
                  {formatBytes((t.data_bytes ?? 0) + (t.index_bytes ?? 0))}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
