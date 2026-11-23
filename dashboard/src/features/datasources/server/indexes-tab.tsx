import { CheckCircle2, Copy, Gauge, KeyRound, Link2, ScanSearch, TriangleAlert, Unplug } from 'lucide-react'
import { useMemo, useState } from 'react'

import { SearchInput } from '@/components/search-input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ColumnList, FindingRow, FindingSection, QualifiedName } from '@/features/datasources/server/parts'
import { formatBytes, formatCompact, formatCount, formatDate } from '@/lib/format'
import type { IndexesData } from '@/lib/types'

export function IndexesTab({ data }: { data: IndexesData }) {
  const since = data.usage_since ? formatDate(data.usage_since) : null
  const problems =
    data.invalid.length +
    data.full_scans.length +
    data.unindexed_foreign_keys.length +
    data.missing_primary_keys.length +
    data.duplicates.length +
    data.unused.length

  return (
    <div className="grid gap-4">
      {problems === 0 && (
        <p className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 text-sm">
          <CheckCircle2 className="size-4 text-success" aria-hidden />
          No index problems found.
        </p>
      )}

      {data.invalid.length > 0 && (
        <FindingSection
          icon={TriangleAlert}
          title="Broken indexes"
          count={data.invalid.length}
          why="Left by a failed index build: they slow every write and are never used."
        >
          {data.invalid.map((f) => (
            <FindingRow key={`${f.schema}.${f.index}`} name={f.index} sub={<QualifiedName schema={f.schema} name={f.table} />} />
          ))}
        </FindingSection>
      )}

      {data.full_scans.length > 0 && (
        <FindingSection
          icon={ScanSearch}
          title="Big tables read in full"
          count={data.full_scans.length}
          why="Queries read these tables row by row. A missing index is the usual cause; the Queries tab shows which statements."
        >
          {data.full_scans.map((f) => (
            <FindingRow
              key={`${f.schema}.${f.table}`}
              name={<QualifiedName schema={f.schema} name={f.table} />}
              sub={f.rows != null ? `${formatCompact(f.rows)} rows` : undefined}
              aside={
                f.full_scans != null
                  ? `${formatCompact(f.full_scans)} full scans`
                  : f.rows_read_without_index != null
                    ? `${formatCompact(f.rows_read_without_index)} rows read without an index`
                    : undefined
              }
            />
          ))}
        </FindingSection>
      )}

      {data.unindexed_foreign_keys.length > 0 && (
        <FindingSection
          icon={Link2}
          title="Foreign keys without an index"
          count={data.unindexed_foreign_keys.length}
          why="Joins, and deletes on the referenced table, have to scan this whole table."
        >
          {data.unindexed_foreign_keys.map((f) => (
            <FindingRow
              key={`${f.schema}.${f.table}.${f.constraint}`}
              name={<QualifiedName schema={f.schema} name={f.table} />}
              sub={
                <>
                  <ColumnList columns={f.columns} /> → {f.references}
                </>
              }
            />
          ))}
        </FindingSection>
      )}

      {data.missing_primary_keys.length > 0 && (
        <FindingSection
          icon={KeyRound}
          title="Tables without a primary key"
          count={data.missing_primary_keys.length}
          why="Rows cannot be identified reliably; updates, replication and many tools suffer."
        >
          {data.missing_primary_keys.map((f) => (
            <FindingRow
              key={`${f.schema}.${f.table}`}
              name={<QualifiedName schema={f.schema} name={f.table} />}
              aside={f.rows != null ? `${formatCompact(f.rows)} rows` : undefined}
            />
          ))}
        </FindingSection>
      )}

      {data.duplicates.length > 0 && (
        <FindingSection
          icon={Copy}
          title="Duplicate indexes"
          count={data.duplicates.length}
          why="Another index already starts with the same columns, so this one only costs disk and slows writes."
        >
          {data.duplicates.map((f) => (
            <FindingRow
              key={`${f.schema}.${f.table}.${f.index}`}
              name={f.index}
              sub={
                <>
                  <QualifiedName schema={f.schema} name={f.table} /> <ColumnList columns={f.columns} /> · covered by{' '}
                  <span className="font-mono">{f.covered_by}</span>
                </>
              }
              aside={f.size_bytes != null ? formatBytes(f.size_bytes) : undefined}
            />
          ))}
        </FindingSection>
      )}

      {data.unused.length > 0 && (
        <FindingSection
          icon={Unplug}
          title={since ? `Not used since ${since}` : 'Unused indexes'}
          count={data.unused.length}
          why="Usage counters restart when the server restarts. Check over a month of normal traffic before removing one; month-end reports may need it."
        >
          {data.unused.map((f) => (
            <FindingRow
              key={`${f.schema}.${f.table}.${f.index}`}
              name={f.index}
              sub={
                <>
                  <QualifiedName schema={f.schema} name={f.table} /> <ColumnList columns={f.columns} />
                </>
              }
              aside={f.size_bytes != null ? formatBytes(f.size_bytes) : undefined}
            />
          ))}
        </FindingSection>
      )}

      <AllIndexes data={data} />
    </div>
  )
}

const PAGE = 50

function AllIndexes({ data }: { data: IndexesData }) {
  const [search, setSearch] = useState('')
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return data.indexes
    return data.indexes.filter((i) => `${i.schema}.${i.table}.${i.name} ${i.columns.join(' ')}`.toLowerCase().includes(q))
  }, [data.indexes, search])
  const [limit, setLimit] = useState(PAGE)
  const hasSizes = data.indexes.some((i) => i.size_bytes != null)
  const visible = shown.slice(0, limit)

  return (
    <section className="grid gap-3" aria-labelledby="all-indexes">
      <div className="mt-2 flex flex-wrap items-end justify-between gap-2">
        <h3 id="all-indexes" className="flex items-center gap-2 text-sm font-medium">
          <Gauge className="size-4 text-muted-foreground" aria-hidden />
          All indexes
        </h3>
        <p className="text-xs text-muted-foreground">
          {data.truncated ? `First ${formatCount(data.indexes.length)}` : formatCount(data.total_indexes)} indexes
        </p>
      </div>
      <SearchInput value={search} onValueChange={setSearch} placeholder="Search indexes" aria-label="Search indexes" />
      <Card className="overflow-hidden">
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Index</TableHead>
                <TableHead>Table</TableHead>
                <TableHead>Columns</TableHead>
                {hasSizes && <TableHead className="text-right">Size</TableHead>}
                <TableHead className="text-right">Used</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((i) => (
                <TableRow key={`${i.schema}.${i.table}.${i.name}`}>
                  <TableCell className="max-w-56">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate font-mono text-sm" title={i.name}>
                        {i.name}
                      </span>
                      {i.primary ? <Badge variant="secondary">Primary</Badge> : i.unique && <Badge variant="secondary">Unique</Badge>}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-56 truncate font-mono text-sm">
                    <QualifiedName schema={i.schema} name={i.table} />
                  </TableCell>
                  <TableCell className="max-w-56 truncate text-sm text-muted-foreground">
                    <ColumnList columns={i.columns} />
                  </TableCell>
                  {hasSizes && (
                    <TableCell className="text-right tabular-nums">
                      {i.size_bytes != null ? formatBytes(i.size_bytes) : '—'}
                    </TableCell>
                  )}
                  <TableCell className="text-right text-muted-foreground tabular-nums">
                    {i.scans != null ? formatCompact(i.scans) : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <ul className="divide-y md:hidden">
          {visible.map((i) => (
            <FindingRow
              key={`${i.schema}.${i.table}.${i.name}`}
              name={i.name}
              sub={
                <>
                  <QualifiedName schema={i.schema} name={i.table} /> <ColumnList columns={i.columns} />
                </>
              }
              aside={i.scans != null ? `used ${formatCompact(i.scans)}×` : undefined}
            />
          ))}
        </ul>
        {shown.length === 0 && <p className="p-4 text-sm text-muted-foreground">No index matches.</p>}
        {shown.length > limit && (
          <div className="border-t px-2 py-1.5">
            <Button variant="ghost" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
              Show {Math.min(PAGE, shown.length - limit)} more of {shown.length - limit}
            </Button>
          </div>
        )}
      </Card>
    </section>
  )
}
