"""MySQL / MariaDB collectors. Every statement is a fixed, read-only SELECT or SHOW.

Sources (all visible to the monitoring user from the README, none of them reads table rows):
    SHOW GLOBAL STATUS / VARIABLES, SHOW REPLICA STATUS        -> health
    information_schema.TABLES, TABLE_CONSTRAINTS               -> table_stats
    information_schema.STATISTICS, KEY_COLUMN_USAGE,
    performance_schema.table_io_waits_summary_by_index_usage  -> indexes
    performance_schema.events_statements_summary_by_digest    -> slow_queries
    performance_schema.data_lock_waits / data_locks,
    information_schema.INNODB_TRX, PROCESSLIST                 -> locks
    information_schema.TABLES                                  -> table_index
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import aiomysql

from zipzy_connector.collectors.analysis import (
    FULL_SCAN_MIN_ROWS,
    MAX_FINDINGS,
    duplicate_indexes,
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
    since_uptime,
    unavailable,
)
from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.mysql import connect_mysql

MAX_TABLES = 200
MAX_INDEXES = 500
SCAN_LIMIT = 5000  # most index / foreign-key rows read for the analysis
SEP = "\x1f"  # column-list separator that cannot appear in a column name

_STATUS = (
    "Uptime",
    "Threads_connected",
    "Threads_running",
    "Max_used_connections",
    "Questions",
    "Slow_queries",
    "Innodb_buffer_pool_read_requests",
    "Innodb_buffer_pool_reads",
    "Created_tmp_tables",
    "Created_tmp_disk_tables",
    "Aborted_connects",
)
_SETTINGS = (
    "max_connections",
    "innodb_buffer_pool_size",
    "slow_query_log",
    "long_query_time",
    "performance_schema",
)


async def _rows(conn: Any, sql: str, args: tuple[Any, ...] | None = None) -> list[Any]:
    async with conn.cursor() as cur:
        await cur.execute(sql, args)
        return list(await cur.fetchall())


async def _named(conn: Any, sql: str) -> dict[str, str]:
    return {str(k): str(v) for k, v in await _rows(conn, sql)}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _replication(conn: Any) -> dict[str, Any]:
    for statement, lag_key in (
        ("SHOW REPLICA STATUS", "Seconds_Behind_Source"),
        ("SHOW SLAVE STATUS", "Seconds_Behind_Master"),
    ):
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(statement)
                row = await cur.fetchone()
        except aiomysql.Error:
            continue
        if not row:
            return {"is_replica": False, "lag_seconds": None}
        lag = row.get(lag_key)
        return {"is_replica": True, "lag_seconds": None if lag is None else float(lag)}
    return {"is_replica": None, "lag_seconds": None}  # not allowed to look


async def health(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        everything = await _named(conn, "SHOW GLOBAL STATUS")
        status = {k: v for k, v in everything.items() if k in _STATUS}
        variables = await _named(conn, "SHOW GLOBAL VARIABLES")
        settings = {k: v for k, v in variables.items() if k in _SETTINGS}
        deadlocks = None
        try:
            rows = await _rows(
                conn,
                "SELECT `COUNT` FROM information_schema.INNODB_METRICS "
                "WHERE NAME = 'lock_deadlocks'",
            )
            deadlocks = _int(rows[0][0]) if rows else None
        except aiomysql.Error:
            pass
        replication = await _replication(conn)
    finally:
        conn.close()

    uptime = _int(status.get("Uptime"))
    reads = _int(status.get("Innodb_buffer_pool_read_requests")) or 0
    misses = _int(status.get("Innodb_buffer_pool_reads")) or 0
    tmp = _int(status.get("Created_tmp_tables")) or 0
    tmp_disk = _int(status.get("Created_tmp_disk_tables")) or 0
    questions = _int(status.get("Questions"))
    return {
        "uptime_seconds": uptime,
        "connections": {
            "current": _int(status.get("Threads_connected")),
            # Threads_running counts this connector's own query too.
            "active": max((_int(status.get("Threads_running")) or 1) - 1, 0),
            "max": _int(settings.get("max_connections")),
            "peak": _int(status.get("Max_used_connections")),
        },
        "cache_hit_ratio": round(1 - misses / reads, 4) if reads else None,
        "throughput_per_second": round(questions / uptime, 2) if questions and uptime else None,
        "throughput_unit": "queries",
        "deadlocks": deadlocks,
        "slow_queries": _int(status.get("Slow_queries")),
        "temp_tables_on_disk_ratio": round(tmp_disk / tmp, 4) if tmp else None,
        "replication": replication,
        "settings": settings,
    }


async def table_stats(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        total = await _rows(
            conn,
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA NOT IN "
            "('mysql', 'sys', 'information_schema', 'performance_schema')",
        )
        rows = await _rows(
            conn,
            """
            SELECT t.TABLE_SCHEMA, t.TABLE_NAME, t.ENGINE, t.TABLE_ROWS,
                   t.DATA_LENGTH, t.INDEX_LENGTH, t.DATA_FREE,
                   EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS c
                           WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
                             AND c.CONSTRAINT_TYPE = 'PRIMARY KEY')
            FROM information_schema.TABLES t
            WHERE t.TABLE_TYPE = 'BASE TABLE' AND t.TABLE_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema')
            ORDER BY COALESCE(t.DATA_LENGTH, 0) + COALESCE(t.INDEX_LENGTH, 0) DESC,
                     t.TABLE_SCHEMA, t.TABLE_NAME
            LIMIT %s
            """,
            (MAX_TABLES,),
        )
    finally:
        conn.close()

    total_tables = int(total[0][0]) if total else 0
    return {
        "total_tables": total_tables,
        "truncated": total_tables > len(rows),
        "tables": [
            {
                "schema": str(schema),
                "name": str(name),
                "engine": None if engine is None else str(engine),
                "rows": _int(n_rows),
                "data_bytes": _int(data),
                "index_bytes": _int(index),
                "free_bytes": _int(free),
                "dead_rows": None,
                "has_primary_key": bool(has_pk),
                "seq_scans": None,
                "index_scans": None,
            }
            for schema, name, engine, n_rows, data, index, free, has_pk in rows
        ],
    }


async def indexes(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        index_rows = await _rows(
            conn,
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, MIN(NON_UNIQUE),
                   GROUP_CONCAT(COALESCE(COLUMN_NAME, '') ORDER BY SEQ_IN_INDEX SEPARATOR %s),
                   MAX(COLUMN_NAME IS NULL)
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema')
            GROUP BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME
            ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME
            LIMIT %s
            """,
            (SEP, SCAN_LIMIT),
        )
        fk_rows = await _rows(
            conn,
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME,
                   GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR %s),
                   MAX(CONCAT(REFERENCED_TABLE_SCHEMA, '.', REFERENCED_TABLE_NAME))
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE REFERENCED_TABLE_NAME IS NOT NULL AND TABLE_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema')
            GROUP BY TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME
            LIMIT %s
            """,
            (SEP, SCAN_LIMIT),
        )
        no_pk_rows = await _rows(
            conn,
            """
            SELECT t.TABLE_SCHEMA, t.TABLE_NAME, t.TABLE_ROWS
            FROM information_schema.TABLES t
            WHERE t.TABLE_TYPE = 'BASE TABLE' AND t.TABLE_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema')
              AND NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS c
                              WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA
                                AND c.TABLE_NAME = t.TABLE_NAME
                                AND c.CONSTRAINT_TYPE = 'PRIMARY KEY')
            ORDER BY t.TABLE_ROWS DESC
            LIMIT %s
            """,
            (MAX_FINDINGS,),
        )
        usage: dict[tuple[str, str, str], int] = {}
        full_scans: list[Any] = []
        uptime_rows: list[Any] = []
        try:
            for schema, table, index, count in await _rows(
                conn,
                """
                SELECT OBJECT_SCHEMA, OBJECT_NAME, INDEX_NAME, COUNT_STAR
                FROM performance_schema.table_io_waits_summary_by_index_usage
                WHERE INDEX_NAME IS NOT NULL AND OBJECT_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema')
                LIMIT %s
                """,
                (SCAN_LIMIT,),
            ):
                usage[(str(schema), str(table), str(index))] = int(count)
            full_scans = await _rows(
                conn,
                """
                SELECT u.OBJECT_SCHEMA, u.OBJECT_NAME, u.COUNT_READ, t.TABLE_ROWS
                FROM performance_schema.table_io_waits_summary_by_index_usage u
                JOIN information_schema.TABLES t
                  ON t.TABLE_SCHEMA = u.OBJECT_SCHEMA AND t.TABLE_NAME = u.OBJECT_NAME
                WHERE u.INDEX_NAME IS NULL AND u.COUNT_READ > 0
                  AND u.OBJECT_SCHEMA NOT IN ('mysql', 'sys',
                'information_schema', 'performance_schema') AND t.TABLE_ROWS >= %s
                ORDER BY u.COUNT_READ DESC
                LIMIT %s
                """,
                (FULL_SCAN_MIN_ROWS, MAX_FINDINGS),
            )
            uptime_rows = await _rows(conn, "SHOW GLOBAL STATUS WHERE Variable_name = 'Uptime'")
            usage_known = True
        except aiomysql.Error:
            usage_known = False  # performance_schema off or not readable
    finally:
        conn.close()

    found: list[dict[str, Any]] = []
    for schema, table, name, non_unique, cols, has_expression in index_rows:
        key = (str(schema), str(table), str(name))
        found.append(
            {
                "schema": key[0],
                "table": key[1],
                "name": key[2],
                "columns": [c for c in str(cols).split(SEP) if c],
                "unique": int(non_unique) == 0,
                "primary": key[2] == "PRIMARY",
                "size_bytes": None,  # MySQL does not expose per-index size to this user
                # Not in the usage table: never touched since start (if usage is known).
                "scans": usage.get(key, 0) if usage_known else None,
                "valid": True,
                "partial": False,
                "expression": bool(has_expression),
            }
        )
    foreign_keys = [
        {
            "schema": str(s),
            "table": str(t),
            "name": str(n),
            "columns": [c for c in str(cols).split(SEP) if c],
            "references": str(ref),
        }
        for s, t, n, cols, ref in fk_rows
    ]

    uptime = int(uptime_rows[0][1]) if uptime_rows else None
    since = (
        (datetime.now(UTC) - timedelta(seconds=uptime)).isoformat(timespec="seconds")
        if uptime is not None
        else None
    )
    return {
        "usage_since": since,  # usage counters restart with the server
        "total_indexes": len(found),
        "truncated": len(index_rows) >= SCAN_LIMIT,
        "indexes": found[:MAX_INDEXES],
        "unused": unused_indexes(found) if usage_known else [],
        "duplicates": duplicate_indexes(found),
        "unindexed_foreign_keys": unindexed_foreign_keys(foreign_keys, found),
        "missing_primary_keys": [
            {"schema": str(s), "table": str(t), "rows": _int(r)} for s, t, r in no_pk_rows
        ],
        "full_scans": [
            {
                "schema": str(s),
                "table": str(t),
                "rows": _int(n),
                "full_scans": None,
                "rows_read_without_index": _int(read),
            }
            for s, t, read, n in full_scans
        ],
        "invalid": [],
    }


# ---- slow_queries --------------------------------------------------------------------------------
# performance_schema keeps one row per *normalized* statement ("digest"): every literal value is
# replaced by "?", so no customer data is in the text. Only application statements are listed;
# the connector's own questions (SHOW, information_schema, performance_schema) are left out.

# The two statements below share the same WHERE clause (kept literal so the SQL stays static).
_SLOW_SQL = """
SELECT SCHEMA_NAME, DIGEST, DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT, AVG_TIMER_WAIT,
       MAX_TIMER_WAIT, SUM_ROWS_EXAMINED, SUM_ROWS_SENT, SUM_NO_INDEX_USED,
       SUM_CREATED_TMP_DISK_TABLES
FROM performance_schema.events_statements_summary_by_digest
WHERE DIGEST_TEXT IS NOT NULL
  AND (DIGEST_TEXT LIKE 'SELECT %%' OR DIGEST_TEXT LIKE 'INSERT %%'
       OR DIGEST_TEXT LIKE 'UPDATE %%' OR DIGEST_TEXT LIKE 'DELETE %%'
       OR DIGEST_TEXT LIKE 'REPLACE %%' OR DIGEST_TEXT LIKE 'WITH %%')
  AND DIGEST_TEXT NOT LIKE '%%information_schema%%'
  AND DIGEST_TEXT NOT LIKE '%%performance_schema%%'
  AND (SCHEMA_NAME IS NULL OR SCHEMA_NAME NOT IN ('mysql', 'sys', 'information_schema',
       'performance_schema'))
ORDER BY SUM_TIMER_WAIT DESC
LIMIT %s
"""

_SLOW_COUNT_SQL = """
SELECT COUNT(*)
FROM performance_schema.events_statements_summary_by_digest
WHERE DIGEST_TEXT IS NOT NULL
  AND (DIGEST_TEXT LIKE 'SELECT %%' OR DIGEST_TEXT LIKE 'INSERT %%'
       OR DIGEST_TEXT LIKE 'UPDATE %%' OR DIGEST_TEXT LIKE 'DELETE %%'
       OR DIGEST_TEXT LIKE 'REPLACE %%' OR DIGEST_TEXT LIKE 'WITH %%')
  AND DIGEST_TEXT NOT LIKE '%%information_schema%%'
  AND DIGEST_TEXT NOT LIKE '%%performance_schema%%'
  AND (SCHEMA_NAME IS NULL OR SCHEMA_NAME NOT IN ('mysql', 'sys', 'information_schema',
       'performance_schema'))
"""

PICO_PER_MS = 1_000_000_000  # performance_schema timers are in picoseconds


def _ms(picoseconds: Any) -> float | None:
    value = _int(picoseconds)
    return None if value is None else round(value / PICO_PER_MS, 3)


async def slow_queries(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        try:
            total = await _rows(conn, _SLOW_COUNT_SQL, ())
            rows = await _rows(conn, _SLOW_SQL, (MAX_QUERIES,))
        except aiomysql.Error:
            return unavailable(
                "performance_schema is off or not readable by the monitoring user "
                "(turn on performance_schema and GRANT SELECT ON performance_schema.*)."
            )
        uptime_rows = await _rows(conn, "SHOW GLOBAL STATUS WHERE Variable_name = 'Uptime'")
    finally:
        conn.close()

    uptime = _int(uptime_rows[0][1]) if uptime_rows else None
    return {
        "available": True,
        "reason": None,
        "since": since_uptime(uptime),
        "total_statements": int(total[0][0]) if total else 0,
        "queries": [
            {
                "id": str(digest),
                "database": None if schema is None else str(schema),
                "text": clip_text(str(text)),
                "calls": _int(calls) or 0,
                "total_ms": _ms(total_wait) or 0.0,
                "mean_ms": _ms(avg_wait) or 0.0,
                "max_ms": _ms(max_wait),
                "rows_returned": _int(sent),
                "rows_examined": _int(examined),
                "no_index_used": _int(no_index),
                "tmp_disk_tables": _int(tmp_disk),
                "disk_blocks_read": None,
            }
            for (
                schema,
                digest,
                text,
                calls,
                total_wait,
                avg_wait,
                max_wait,
                examined,
                sent,
                no_index,
                tmp_disk,
            ) in rows
        ],
    }


# ---- locks -------------------------------------------------------------------------------------
# Who is waiting for whom right now, and transactions left open for a long time. Session ids,
# users, tables and timings only: the statements themselves (with their values) are never read.

_LOCK_WAITS_SQL = """
SELECT r.trx_mysql_thread_id, TIMESTAMPDIFF(SECOND, r.trx_wait_started, NOW()),
       b.trx_mysql_thread_id, TIMESTAMPDIFF(SECOND, b.trx_started, NOW()), b.trx_state,
       l.OBJECT_SCHEMA, l.OBJECT_NAME, l.INDEX_NAME, l.LOCK_MODE
FROM performance_schema.data_lock_waits w
JOIN information_schema.INNODB_TRX r ON r.trx_id = w.REQUESTING_ENGINE_TRANSACTION_ID
JOIN information_schema.INNODB_TRX b ON b.trx_id = w.BLOCKING_ENGINE_TRANSACTION_ID
LEFT JOIN performance_schema.data_locks l ON l.ENGINE_LOCK_ID = w.REQUESTING_ENGINE_LOCK_ID
ORDER BY r.trx_wait_started
LIMIT %s
"""

_LONG_TRX_SQL = """
SELECT t.trx_mysql_thread_id, TIMESTAMPDIFF(SECOND, t.trx_started, NOW()), t.trx_state,
       t.trx_rows_locked, t.trx_rows_modified, p.USER, p.DB
FROM information_schema.INNODB_TRX t
LEFT JOIN information_schema.PROCESSLIST p ON p.ID = t.trx_mysql_thread_id
WHERE t.trx_started < NOW() - INTERVAL %s SECOND AND t.trx_mysql_thread_id <> CONNECTION_ID()
ORDER BY t.trx_started
LIMIT %s
"""


async def locks(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        try:
            waits = await _rows(conn, _LOCK_WAITS_SQL, (MAX_LOCK_ROWS,))
        except aiomysql.Error:
            # MariaDB and MySQL 5.7 have no data_lock_waits; performance_schema may be off.
            return unavailable(
                "Lock details need MySQL 8.0 or newer with performance_schema on, "
                "readable by the monitoring user."
            )
        long_trx = await _rows(conn, _LONG_TRX_SQL, (LONG_TRANSACTION_SECONDS, MAX_LOCK_ROWS))
    finally:
        conn.close()

    return {
        "available": True,
        "reason": None,
        "long_transaction_seconds": LONG_TRANSACTION_SECONDS,
        "waits": [
            {
                "waiting_session": _int(waiting),
                "wait_seconds": _int(wait_s),
                "blocking_session": _int(blocking),
                "blocker_transaction_seconds": _int(blocker_s),
                "blocker_state": None if state is None else str(state),
                "schema": None if schema is None else str(schema),
                "table": None if table is None else str(table),
                "index": None if index is None else str(index),
                "lock_mode": None if mode is None else str(mode),
            }
            for waiting, wait_s, blocking, blocker_s, state, schema, table, index, mode in waits
        ],
        "long_transactions": [
            {
                "session": _int(session),
                "seconds": _int(seconds),
                "state": None if state is None else str(state),
                "rows_locked": _int(locked),
                "rows_modified": _int(modified),
                "user": None if user is None else str(user),
                "database": None if dbname is None else str(dbname),
            }
            for session, seconds, state, locked, modified, user, dbname in long_trx
        ],
    }


# ---- table_index -------------------------------------------------------------------------------
# Every table's name, estimated rows and size, biggest first, so ZipZy can find "attendance"
# among thousands of tables without asking the server again. Compact: one short list per table.

_TABLE_INDEX_SQL = """
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS,
       COALESCE(DATA_LENGTH, 0) + COALESCE(INDEX_LENGTH, 0)
FROM information_schema.TABLES
WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA NOT IN ('mysql', 'sys',
    'information_schema', 'performance_schema')
ORDER BY 4 DESC, 1, 2
LIMIT %s
"""


async def table_index(db: DatabaseConfig, password: str) -> dict[str, Any]:
    conn = await connect_mysql(db, password)
    try:
        total = await _rows(
            conn,
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA NOT IN "
            "('mysql', 'sys', 'information_schema', 'performance_schema')",
        )
        rows = await _rows(conn, _TABLE_INDEX_SQL, (MAX_TABLE_INDEX,))
    finally:
        conn.close()
    return build_table_index(
        int(total[0][0]) if total else 0,
        ((str(s), str(n), _int(r), _int(b)) for s, n, r, b in rows),
    )
