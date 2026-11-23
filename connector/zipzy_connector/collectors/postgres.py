"""PostgreSQL collectors. Every statement is a fixed, read-only SELECT on the statistics views.

Needs the monitoring user from the README (pg_monitor). Per-table statistics exist only for the
database the connector logs in to, so table_stats and indexes describe that database.
slow_queries reads pg_stat_statements (all databases) when that extension is installed.
"""

import re
from datetime import datetime
from typing import Any

import asyncpg

from zipzy_connector.collectors.analysis import (
    FULL_SCAN_MIN_ROWS,
    MAX_FINDINGS,
    duplicate_indexes,
    invalid_indexes,
    unindexed_foreign_keys,
    unused_indexes,
)
from zipzy_connector.collectors.shared import (
    LONG_TRANSACTION_SECONDS,
    MAX_LOCK_ROWS,
    MAX_QUERIES,
    MAX_TABLE_INDEX,
    build_table_index,
    clip_text,
    unavailable,
)
from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.postgres import connect_postgres

MAX_TABLES = 200
MAX_INDEXES = 500
SCAN_LIMIT = 5000

_SETTINGS = (
    "max_connections",
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "autovacuum",
    "log_min_duration_statement",
)

_HEALTH_SQL = r"""
select
  extract(epoch from now() - pg_postmaster_start_time())::bigint as uptime,
  (select count(*) from pg_stat_activity where backend_type = 'client backend') as current,
  (select count(*) from pg_stat_activity
     where backend_type = 'client backend' and state = 'active') as active,
  current_setting('max_connections')::int as max,
  (select sum(blks_hit)::float8 / nullif(sum(blks_hit) + sum(blks_read), 0)
     from pg_stat_database) as hit,
  (select sum(xact_commit + xact_rollback) from pg_stat_database) as xacts,
  (select sum(deadlocks) from pg_stat_database) as deadlocks,
  (select sum(temp_files) from pg_stat_database) as temp_files,
  pg_is_in_recovery() as is_replica,
  case when pg_is_in_recovery()
       then extract(epoch from now() - pg_last_xact_replay_timestamp()) end as lag
"""

_SETTINGS_SQL = r"""
select name, current_setting(name) as value from pg_settings where name = any($1::text[])
"""

_TABLES_SQL = r"""
select n.nspname as schema, c.relname as name,
       coalesce(s.n_live_tup, nullif(c.reltuples, -1)::bigint) as rows,
       pg_table_size(c.oid) as data_bytes, pg_indexes_size(c.oid) as index_bytes,
       s.n_dead_tup as dead_rows, s.seq_scan, s.idx_scan,
       exists (select 1 from pg_index i where i.indrelid = c.oid and i.indisprimary) as has_pk
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_stat_user_tables s on s.relid = c.oid
where c.relkind in ('r', 'p')
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg\_toast%'
order by pg_total_relation_size(c.oid) desc, n.nspname, c.relname
limit $1
"""

_TABLE_COUNT_SQL = r"""
select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('r', 'p')
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg\_toast%'
"""

_INDEXES_SQL = r"""
select n.nspname as schema, t.relname as table, i.relname as name,
       ix.indisunique as unique, ix.indisprimary as primary, ix.indisvalid as valid,
       ix.indpred is not null as partial, ix.indexprs is not null as expression,
       array(select a.attname from unnest(ix.indkey) with ordinality k(attnum, ord)
             join pg_attribute a on a.attrelid = t.oid and a.attnum = k.attnum
             order by k.ord) as columns,
       pg_relation_size(i.oid) as size_bytes, s.idx_scan as scans
from pg_index ix
join pg_class i on i.oid = ix.indexrelid
join pg_class t on t.oid = ix.indrelid
join pg_namespace n on n.oid = t.relnamespace
left join pg_stat_user_indexes s on s.indexrelid = ix.indexrelid
where n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg\_toast%'
order by pg_relation_size(i.oid) desc, n.nspname, t.relname, i.relname
limit $1
"""

_FOREIGN_KEYS_SQL = r"""
select n.nspname as schema, t.relname as table, c.conname as name,
       array(select a.attname from unnest(c.conkey) with ordinality k(attnum, ord)
             join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum
             order by k.ord) as columns,
       rn.nspname || '.' || rt.relname as references
from pg_constraint c
join pg_class t on t.oid = c.conrelid
join pg_namespace n on n.oid = t.relnamespace
join pg_class rt on rt.oid = c.confrelid
join pg_namespace rn on rn.oid = rt.relnamespace
where c.contype = 'f'
  and n.nspname not in ('pg_catalog', 'information_schema')
limit $1
"""

_NO_PK_SQL = r"""
select n.nspname as schema, c.relname as table,
       coalesce(s.n_live_tup, nullif(c.reltuples, -1)::bigint) as rows
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_stat_user_tables s on s.relid = c.oid
where not exists (select 1 from pg_index i where i.indrelid = c.oid and i.indisprimary)
  and c.relispartition is false
  and c.relkind in ('r', 'p')
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg\_toast%'
order by 3 desc nulls last
limit $1
"""

_FULL_SCANS_SQL = r"""
select schemaname as schema, relname as table, n_live_tup as rows, seq_scan, idx_scan
from pg_stat_user_tables
where n_live_tup >= $1 and seq_scan >= 50 and seq_scan > coalesce(idx_scan, 0)
order by seq_scan * n_live_tup desc
limit $2
"""

_STATS_SINCE_SQL = r"""
select coalesce(
  (select stats_reset from pg_stat_database where datname = current_database()),
  pg_postmaster_start_time())
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


async def health(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        h = await conn.fetchrow(_HEALTH_SQL)
        settings = {r["name"]: r["value"] for r in await conn.fetch(_SETTINGS_SQL, _SETTINGS)}
    finally:
        await conn.close()
    uptime = int(h["uptime"]) if h["uptime"] is not None else None
    xacts = int(h["xacts"]) if h["xacts"] is not None else None
    return {
        "uptime_seconds": uptime,
        "connections": {
            "current": int(h["current"]),
            "active": int(h["active"]),
            "max": int(h["max"]),
            "peak": None,
        },
        "cache_hit_ratio": round(float(h["hit"]), 4) if h["hit"] is not None else None,
        "throughput_per_second": round(xacts / uptime, 2) if xacts and uptime else None,
        "throughput_unit": "transactions",
        "deadlocks": int(h["deadlocks"]) if h["deadlocks"] is not None else None,
        "slow_queries": None,
        "temp_tables_on_disk_ratio": None,
        "replication": {
            "is_replica": bool(h["is_replica"]),
            "lag_seconds": float(h["lag"]) if h["lag"] is not None else None,
        },
        "settings": settings,
    }


async def table_stats(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        total = int(await conn.fetchval(_TABLE_COUNT_SQL))
        rows = await conn.fetch(_TABLES_SQL, MAX_TABLES)
    finally:
        await conn.close()
    return {
        "total_tables": total,
        "truncated": total > len(rows),
        "tables": [
            {
                "schema": r["schema"],
                "name": r["name"],
                "engine": None,
                "rows": r["rows"],
                "data_bytes": r["data_bytes"],
                "index_bytes": r["index_bytes"],
                "free_bytes": None,
                "dead_rows": r["dead_rows"],
                "has_primary_key": bool(r["has_pk"]),
                "seq_scans": r["seq_scan"],
                "index_scans": r["idx_scan"],
            }
            for r in rows
        ],
    }


async def indexes(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        index_rows = await conn.fetch(_INDEXES_SQL, SCAN_LIMIT)
        fk_rows = await conn.fetch(_FOREIGN_KEYS_SQL, SCAN_LIMIT)
        no_pk_rows = await conn.fetch(_NO_PK_SQL, MAX_FINDINGS)
        scan_rows = await conn.fetch(_FULL_SCANS_SQL, FULL_SCAN_MIN_ROWS, MAX_FINDINGS)
        since = await conn.fetchval(_STATS_SINCE_SQL)
    finally:
        await conn.close()

    found = [
        {
            "schema": r["schema"],
            "table": r["table"],
            "name": r["name"],
            "columns": list(r["columns"]),
            "unique": bool(r["unique"]),
            "primary": bool(r["primary"]),
            "size_bytes": r["size_bytes"],
            "scans": r["scans"],
            "valid": bool(r["valid"]),
            "partial": bool(r["partial"]),
            "expression": bool(r["expression"]),
        }
        for r in index_rows
    ]
    foreign_keys = [
        {
            "schema": r["schema"],
            "table": r["table"],
            "name": r["name"],
            "columns": list(r["columns"]),
            "references": r["references"],
        }
        for r in fk_rows
    ]
    return {
        "usage_since": _iso(since),
        "total_indexes": len(found),
        "truncated": len(index_rows) >= SCAN_LIMIT,
        "indexes": found[:MAX_INDEXES],
        "unused": unused_indexes(found),
        "duplicates": duplicate_indexes(found),
        "unindexed_foreign_keys": unindexed_foreign_keys(foreign_keys, found),
        "missing_primary_keys": [
            {"schema": r["schema"], "table": r["table"], "rows": r["rows"]} for r in no_pk_rows
        ],
        "full_scans": [
            {
                "schema": r["schema"],
                "table": r["table"],
                "rows": r["rows"],
                "full_scans": r["seq_scan"],
                "rows_read_without_index": None,
            }
            for r in scan_rows
        ],
        "invalid": invalid_indexes(found),
    }


# ---- slow_queries --------------------------------------------------------------------------------
# pg_stat_statements keeps one row per *normalized* statement: constants become $1, $2 …, so no
# customer data is in the text. Only application statements (SELECT/INSERT/UPDATE/DELETE/WITH/
# MERGE) are listed; utility statements are skipped because PostgreSQL may keep their literals
# (for example a password in CREATE ROLE), and the connector's own catalog questions are skipped.

_PGSS_SCHEMA_SQL = r"""
select n.nspname from pg_extension e join pg_namespace n on n.oid = e.extnamespace
where e.extname = 'pg_stat_statements'
"""

_APP_STATEMENT = r"^\s*(select|insert|update|delete|with|merge)\M"
_OWN_QUESTIONS = r"\m(pg_catalog|information_schema|pg_stat_\w+|pg_class|pg_namespace|pg_index)\M"

_SLOW_SQL = r"""
select s.queryid::text as id, d.datname as database, s.query as text, s.calls,
       s.total_exec_time as total_ms, s.mean_exec_time as mean_ms, s.max_exec_time as max_ms,
       s.rows as rows_returned, s.shared_blks_read as disk_blocks_read
from {schema}.pg_stat_statements s
left join pg_database d on d.oid = s.dbid
where s.query ~* $1 and s.query !~* $2
order by s.total_exec_time desc
limit $3
"""

_SLOW_COUNT_SQL = r"""
select count(*) from {schema}.pg_stat_statements s where s.query ~* $1 and s.query !~* $2
"""

_PGSS_SINCE_SQL = "select stats_reset from {schema}.pg_stat_statements_info"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

PGSS_MISSING = (
    "pg_stat_statements is not installed. Add it to shared_preload_libraries, restart "
    "PostgreSQL and run CREATE EXTENSION pg_stat_statements; in this database."
)


async def slow_queries(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        schema = await conn.fetchval(_PGSS_SCHEMA_SQL)
        if schema is None:
            return unavailable(PGSS_MISSING)
        if not _IDENTIFIER.match(schema):
            return unavailable("pg_stat_statements is installed in a schema ZipZy cannot use.")
        try:
            # `schema` comes from the catalog and matched _IDENTIFIER above: no quoting needed.
            total = await conn.fetchval(
                _SLOW_COUNT_SQL.format(schema=schema), _APP_STATEMENT, _OWN_QUESTIONS
            )
            rows = await conn.fetch(
                _SLOW_SQL.format(schema=schema), _APP_STATEMENT, _OWN_QUESTIONS, MAX_QUERIES
            )
        except asyncpg.ObjectNotInPrerequisiteStateError:
            return unavailable(
                "pg_stat_statements is installed but not loaded: add it to "
                "shared_preload_libraries and restart PostgreSQL."
            )
        except asyncpg.UndefinedColumnError:
            return unavailable("Slow queries need PostgreSQL 13 or newer.")
        try:
            since = await conn.fetchval(_PGSS_SINCE_SQL.format(schema=schema))
        except asyncpg.PostgresError:  # pg_stat_statements_info exists from PostgreSQL 14
            since = None
    finally:
        await conn.close()

    return {
        "available": True,
        "reason": None,
        "since": _iso(since),
        "total_statements": int(total),
        "queries": [
            {
                "id": r["id"],
                "database": r["database"],
                "text": clip_text(r["text"]),
                "calls": int(r["calls"]),
                "total_ms": round(float(r["total_ms"]), 3),
                "mean_ms": round(float(r["mean_ms"]), 3),
                "max_ms": round(float(r["max_ms"]), 3),
                "rows_returned": int(r["rows_returned"]),
                "rows_examined": None,
                "no_index_used": None,
                "tmp_disk_tables": None,
                "disk_blocks_read": int(r["disk_blocks_read"]),
            }
            for r in rows
        ],
    }


# ---- locks -------------------------------------------------------------------------------------
# Who is waiting for whom right now, and transactions left open for a long time. Session ids,
# users, tables and timings only: the statements themselves (with their values) are never read.

_LOCK_WAITS_SQL = r"""
select w.pid as waiting, extract(epoch from now() - w.query_start)::bigint as wait_s,
       b.pid as blocking, extract(epoch from now() - b.xact_start)::bigint as blocker_s,
       b.state as blocker_state, n.nspname as schema, c.relname as table, l.mode as lock_mode
from pg_stat_activity w
cross join lateral unnest(pg_blocking_pids(w.pid)) as bp(pid)
join pg_stat_activity b on b.pid = bp.pid
left join lateral (
  select relation, mode from pg_locks
  where pid = w.pid and not granted order by relation nulls last limit 1
) l on true
left join pg_class c on c.oid = l.relation
left join pg_namespace n on n.oid = c.relnamespace
where w.wait_event_type = 'Lock'
order by w.query_start
limit $1
"""

_LONG_TRX_SQL = r"""
select pid, extract(epoch from now() - xact_start)::bigint as seconds, state,
       usename as user, datname as database
from pg_stat_activity
where backend_type = 'client backend' and xact_start is not null
  and xact_start < now() - make_interval(secs => $1) and pid <> pg_backend_pid()
order by xact_start
limit $2
"""


async def locks(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        waits = await conn.fetch(_LOCK_WAITS_SQL, MAX_LOCK_ROWS)
        long_trx = await conn.fetch(_LONG_TRX_SQL, LONG_TRANSACTION_SECONDS, MAX_LOCK_ROWS)
    finally:
        await conn.close()
    return {
        "available": True,
        "reason": None,
        "long_transaction_seconds": LONG_TRANSACTION_SECONDS,
        "waits": [
            {
                "waiting_session": r["waiting"],
                "wait_seconds": r["wait_s"],
                "blocking_session": r["blocking"],
                "blocker_transaction_seconds": r["blocker_s"],
                "blocker_state": r["blocker_state"],
                "schema": r["schema"],
                "table": r["table"],
                "index": None,
                "lock_mode": r["lock_mode"],
            }
            for r in waits
        ],
        "long_transactions": [
            {
                "session": r["pid"],
                "seconds": r["seconds"],
                "state": r["state"],
                "rows_locked": None,
                "rows_modified": None,
                "user": r["user"],
                "database": r["database"],
            }
            for r in long_trx
        ],
    }


# ---- table_index -------------------------------------------------------------------------------
# Every table's name, estimated rows and size (from the catalog, so it stays fast with many
# thousands of tables), biggest first. Partitions are listed too: they are often the monthly
# tables people ask about.

_TABLE_INDEX_SQL = r"""
select n.nspname as schema, c.relname as name, nullif(c.reltuples, -1)::bigint as rows,
       c.relpages::bigint * current_setting('block_size')::bigint as bytes
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('r', 'p')
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg\_toast%'
order by 4 desc, 1, 2
limit $1
"""


async def table_index(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_postgres(db, password)
    try:
        total = int(await conn.fetchval(_TABLE_COUNT_SQL))
        rows = await conn.fetch(_TABLE_INDEX_SQL, MAX_TABLE_INDEX)
    finally:
        await conn.close()
    return build_table_index(total, ((r["schema"], r["name"], r["rows"], r["bytes"]) for r in rows))
