import { ArrowDown, CheckCircle2, Clock, Hourglass, Info, Lock } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { needsIndex, rowsReadPerRun } from '@/features/datasources/server/attention'
import { FindingRow, FindingSection, QualifiedName } from '@/features/datasources/server/parts'
import { formatCompact, formatCount, formatDate, formatMs, formatWait } from '@/lib/format'
import type { LocksData, QueryStat, SlowQueriesData } from '@/lib/types'

type SortKey = 'total' | 'mean' | 'calls'
const SORTS: Record<SortKey, { label: string; compare: (a: QueryStat, b: QueryStat) => number }> = {
  total: { label: 'Total time', compare: (a, b) => b.total_ms - a.total_ms },
  mean: { label: 'Average', compare: (a, b) => b.mean_ms - a.mean_ms },
  calls: { label: 'Runs', compare: (a, b) => b.calls - a.calls },
}

function Notes({ q }: { q: QueryStat }) {
  return (
    <span className="flex flex-wrap gap-1">
      {needsIndex(q) && <Badge variant="warning">Needs an index</Badge>}
      {q.tmp_disk_tables != null && q.tmp_disk_tables > 0 && <Badge variant="secondary">Temp tables on disk</Badge>}
    </span>
  )
}

/** A statement: two lines, click to see all of it. Values are already "?" / "$1". */
function Statement({ q }: { q: QueryStat }) {
  const [open, setOpen] = useState(false)
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      aria-expanded={open}
      title={open ? 'Show less' : 'Show the whole statement'}
      className="block w-full text-left font-mono text-xs [overflow-wrap:anywhere] whitespace-pre-wrap outline-none focus-visible:underline"
    >
      <span className={open ? undefined : 'line-clamp-2'}>{q.text}</span>
      {q.database && <span className="mt-0.5 block text-muted-foreground">in {q.database}</span>}
    </button>
  )
}

function SlowQueries({ data }: { data: SlowQueriesData }) {
  const [sort, setSort] = useState<SortKey>('total')
  const shown = useMemo(() => [...data.queries].sort(SORTS[sort].compare), [data.queries, sort])
  const showRowsRead = data.queries.some((q) => q.rows_examined != null)

  if (data.queries.length === 0)
    return (
      <p className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 text-sm">
        <CheckCircle2 className="size-4 text-success" aria-hidden />
        No application statements recorded yet.
      </p>
    )

  const sortHead = (key: SortKey, width: string) => (
    <TableHead className={`${width} text-right`} aria-sort={sort === key ? 'descending' : undefined}>
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
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 border-b px-4 py-3">
        <Clock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">Statements that take the most time</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Values are replaced by <span className="font-mono">?</span> or <span className="font-mono">$1</span> by
            the database itself, so no customer data is shown here.
          </p>
        </div>
      </div>

      <div className="hidden md:block">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Statement</TableHead>
              {sortHead('calls', 'w-20')}
              {sortHead('mean', 'w-28')}
              {sortHead('total', 'w-32')}
              {showRowsRead && (
                <TableHead className="w-28 text-right" title="Rows the server read per run">
                  Rows read
                </TableHead>
              )}
              <TableHead className="w-36">Notes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((q) => (
              <TableRow key={q.id} className="align-top">
                <TableCell className="whitespace-normal">
                  <Statement q={q} />
                </TableCell>
                <TableCell className="text-right tabular-nums" title={formatCount(q.calls)}>
                  {formatCompact(q.calls)}
                </TableCell>
                <TableCell className="text-right tabular-nums" title={q.max_ms != null ? `Slowest run ${formatMs(q.max_ms)}` : undefined}>
                  {formatMs(q.mean_ms)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatMs(q.total_ms)}</TableCell>
                {showRowsRead && (
                  <TableCell className="text-right text-muted-foreground tabular-nums">
                    {rowsReadPerRun(q) != null ? formatCompact(rowsReadPerRun(q) ?? 0) : '—'}
                  </TableCell>
                )}
                <TableCell className="whitespace-normal">
                  <Notes q={q} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="divide-y md:hidden">
        {shown.map((q) => (
          <li key={q.id} className="grid gap-1.5 p-4">
            <Statement q={q} />
            <p className="text-xs text-muted-foreground tabular-nums">
              {formatCompact(q.calls)} runs · {formatMs(q.mean_ms)} average · {formatMs(q.total_ms)} in total
              {rowsReadPerRun(q) != null && ` · ${formatCompact(rowsReadPerRun(q) ?? 0)} read per run`}
            </p>
            <Notes q={q} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Locks({ data }: { data: LocksData }) {
  return (
    <>
      {data.waits.length === 0 ? (
        <p className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 text-sm">
          <CheckCircle2 className="size-4 text-success" aria-hidden />
          No session was waiting for a lock.
        </p>
      ) : (
        <FindingSection
          icon={Lock}
          title="Sessions waiting for a lock"
          count={data.waits.length}
          why="Another session holds rows these need. Until it commits or rolls back, they wait (or time out)."
        >
          {data.waits.map((w, i) => (
            <FindingRow
              key={`${w.waiting_session}-${w.blocking_session}-${i}`}
              name={w.schema && w.table ? <QualifiedName schema={w.schema} name={w.table} /> : 'A table'}
              sub={`Session ${w.waiting_session ?? '?'} waits for session ${w.blocking_session ?? '?'}${
                w.blocker_state ? ` (${w.blocker_state.toLowerCase()})` : ''
              }`}
              aside={
                <>
                  {w.wait_seconds != null && <p>waiting {formatWait(w.wait_seconds)}</p>}
                  {w.blocker_transaction_seconds != null && (
                    <p>blocker open {formatWait(w.blocker_transaction_seconds)}</p>
                  )}
                </>
              }
            />
          ))}
        </FindingSection>
      )}

      {data.long_transactions.length > 0 && (
        <FindingSection
          icon={Hourglass}
          title="Transactions open for a long time"
          count={data.long_transactions.length}
          why={`Open longer than ${formatWait(data.long_transaction_seconds)}. They can hold locks and stop cleanup; often an app forgot to commit.`}
        >
          {data.long_transactions.map((t, i) => (
            <FindingRow
              key={`${t.session}-${i}`}
              name={`Session ${t.session ?? '?'}`}
              sub={[t.user && `user ${t.user}`, t.database && `in ${t.database}`, t.state?.toLowerCase()]
                .filter(Boolean)
                .join(' · ')}
              aside={
                <>
                  {t.seconds != null && <p>open {formatWait(t.seconds)}</p>}
                  {t.rows_locked != null && t.rows_locked > 0 && <p>{formatCompact(t.rows_locked)} rows locked</p>}
                </>
              }
            />
          ))}
        </FindingSection>
      )}
    </>
  )
}

function Unavailable({ title, reason }: { title: string; reason: string | null }) {
  return (
    <Alert>
      <Info aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{reason ?? 'The server cannot report this.'}</AlertDescription>
    </Alert>
  )
}

export function QueriesTab({ slow, locks }: { slow?: SlowQueriesData; locks?: LocksData }) {
  return (
    <div className="grid gap-4">
      {locks &&
        (locks.available ? <Locks data={locks} /> : <Unavailable title="Locks are not available" reason={locks.reason} />)}
      {slow &&
        (slow.available ? (
          <>
            <SlowQueries data={slow} />
            <p className="text-xs text-muted-foreground">
              {slow.queries.length < slow.total_statements
                ? `The ${formatCount(slow.queries.length)} slowest of ${formatCount(slow.total_statements)} statements`
                : `${formatCount(slow.total_statements)} statements`}
              {slow.since ? `, counted since ${formatDate(slow.since)}` : ''}.
            </p>
          </>
        ) : (
          <Unavailable title="Slow queries are not available" reason={slow.reason} />
        ))}
    </div>
  )
}
