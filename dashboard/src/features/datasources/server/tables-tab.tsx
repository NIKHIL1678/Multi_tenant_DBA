import { ArrowDown, Table2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { EmptyState } from '@/components/empty-state'
import { SearchInput } from '@/components/search-input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { QualifiedName } from '@/features/datasources/server/parts'
import { formatBytes, formatCompact, formatCount } from '@/lib/format'
import type { TableRow as Row, TableStatsData } from '@/lib/types'

type SortKey = 'size' | 'rows' | 'name'
const SORTS: Record<SortKey, { label: string; compare: (a: Row, b: Row) => number }> = {
  size: { label: 'Total size', compare: (a, b) => total(b) - total(a) },
  rows: { label: 'Rows', compare: (a, b) => (b.rows ?? -1) - (a.rows ?? -1) },
  name: { label: 'Name', compare: (a, b) => `${a.schema}.${a.name}`.localeCompare(`${b.schema}.${b.name}`) },
}

function total(t: Row): number {
  return (t.data_bytes ?? 0) + (t.index_bytes ?? 0)
}

/** Short notes that matter for a DBA: no primary key, space to reclaim, dead rows. */
function Notes({ t }: { t: Row }) {
  return (
    <span className="flex flex-wrap gap-1">
      {!t.has_primary_key && <Badge variant="warning">No primary key</Badge>}
      {t.free_bytes != null && t.free_bytes > 100 * 1024 ** 2 && (
        <Badge variant="secondary">{formatBytes(t.free_bytes)} free</Badge>
      )}
      {t.dead_rows != null && t.dead_rows > 10_000 && (
        <Badge variant="secondary">{formatCompact(t.dead_rows)} dead rows</Badge>
      )}
    </span>
  )
}

export function TablesTab({ data }: { data: TableStatsData }) {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('size')
  const showScans = data.tables.some((t) => t.seq_scans != null)

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = q ? data.tables.filter((t) => `${t.schema}.${t.name}`.toLowerCase().includes(q)) : data.tables
    return [...list].sort(SORTS[sort].compare)
  }, [data.tables, search, sort])

  if (data.tables.length === 0)
    return <EmptyState icon={Table2} title="No tables" description="This server has no tables outside its system schemas." />

  const sortHead = (key: SortKey, className?: string) => (
    <TableHead className={className} aria-sort={sort === key ? 'descending' : undefined}>
      <button
        type="button"
        onClick={() => setSort(key)}
        className="inline-flex items-center gap-1 uppercase outline-none hover:text-foreground focus-visible:underline"
      >
        {SORTS[key].label}
        {sort === key && <ArrowDown className="size-3" aria-hidden />}
      </button>
    </TableHead>
  )

  return (
    <div className="grid gap-3">
      <SearchInput value={search} onValueChange={setSearch} placeholder="Search tables" aria-label="Search tables" />

      <Card className="overflow-hidden">
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                {sortHead('name')}
                {sortHead('rows', 'text-right')}
                {sortHead('size', 'text-right')}
                <TableHead className="text-right">Of which indexes</TableHead>
                {showScans && <TableHead className="text-right">Full scans</TableHead>}
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((t) => (
                <TableRow key={`${t.schema}.${t.name}`}>
                  <TableCell className="max-w-80 truncate font-mono text-sm">
                    <QualifiedName schema={t.schema} name={t.name} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums" title={t.rows != null ? formatCount(t.rows) : undefined}>
                    {t.rows != null ? formatCompact(t.rows) : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatBytes(total(t))}</TableCell>
                  <TableCell className="text-right text-muted-foreground tabular-nums">
                    {t.index_bytes != null ? formatBytes(t.index_bytes) : '—'}
                  </TableCell>
                  {showScans && (
                    <TableCell className="text-right text-muted-foreground tabular-nums">
                      {t.seq_scans != null ? formatCompact(t.seq_scans) : '—'}
                    </TableCell>
                  )}
                  <TableCell>
                    <Notes t={t} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <ul className="divide-y md:hidden">
          {shown.map((t) => (
            <li key={`${t.schema}.${t.name}`} className="grid gap-1.5 p-4">
              <p className="truncate font-mono text-sm">
                <QualifiedName schema={t.schema} name={t.name} />
              </p>
              <p className="text-xs text-muted-foreground tabular-nums">
                {t.rows != null && `${formatCompact(t.rows)} rows · `}
                {formatBytes(total(t))}
                {t.index_bytes != null && ` (indexes ${formatBytes(t.index_bytes)})`}
              </p>
              <Notes t={t} />
            </li>
          ))}
        </ul>
        {shown.length === 0 && <p className="p-4 text-sm text-muted-foreground">No table matches.</p>}
      </Card>

      <p className="text-xs text-muted-foreground">
        {data.truncated
          ? `The ${formatCount(data.tables.length)} biggest of ${formatCount(data.total_tables)} tables.`
          : `${formatCount(data.total_tables)} tables.`}{' '}
        Row counts are the server’s estimates.
      </p>
    </div>
  )
}
