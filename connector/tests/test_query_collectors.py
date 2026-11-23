"""slow_queries, locks and table_index against real databases, as the monitoring user.

What matters most here: no literal value from a statement ever appears in an answer, the
connector's own questions are not listed, and a server that cannot answer says why.
"""

import asyncio
import json
import os
import warnings
from typing import Any

import aiomysql
import asyncpg
import pytest

from tests.conftest import mysql_config, pg_config
from zipzy_connector.collectors import collect, mysql, postgres
from zipzy_connector.collectors.shared import (
    MAX_TABLE_INDEX,
    MAX_TABLE_INDEX_BYTES,
    build_table_index,
    clip_text,
)
from zipzy_connector.config import DatabaseConfig

SCHEMA = "zipzy_query_test"
SECRET = "secret-value-7731"  # a literal that must never leave the database
FAMILY = ["attendance_2024_01", "attendance_2024_02", "attendance_2024_03"]


# ---- pure helpers ------------------------------------------------------------------------------


def test_table_index_stays_within_count_and_size() -> None:
    rows = ((f"s{i % 7}", "t" * 60 + str(i), i, i * 10) for i in range(MAX_TABLE_INDEX + 5000))
    index = build_table_index(MAX_TABLE_INDEX + 5000, rows)
    assert index["truncated"] is True
    assert index["listed_tables"] == sum(len(s["tables"]) for s in index["schemas"])
    assert index["listed_tables"] <= MAX_TABLE_INDEX
    assert len(json.dumps(index)) <= MAX_TABLE_INDEX_BYTES + 200

    small = build_table_index(2, [("hrm", "a", 1, 10), ("hrm", "b", None, None)])
    assert small == {
        "available": True,
        "reason": None,
        "total_tables": 2,
        "listed_tables": 2,
        "truncated": False,
        "schemas": [{"name": "hrm", "tables": [["a", 1, 10], ["b", None, None]]}],
    }


def test_query_text_is_flattened_and_clipped() -> None:
    assert clip_text("select *\n   from  t") == "select * from t"
    assert len(clip_text("x " * 5000)) == 2000


# ---- MySQL -------------------------------------------------------------------------------------


async def _mysql_admin() -> Any:
    admin = mysql_config("ADMIN")
    return await aiomysql.connect(
        host=admin.host,
        port=admin.effective_port,
        user=admin.user,
        password=admin.resolve_password(),
        autocommit=True,
    )


async def _mysql_setup() -> DatabaseConfig:
    conn = await _mysql_admin()
    try:
        async with conn.cursor() as cur:
            warnings.simplefilter("ignore")
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {SCHEMA}")
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.orders"
                " (id INT PRIMARY KEY, status VARCHAR(40))"
            )
            await cur.execute(f"INSERT IGNORE INTO {SCHEMA}.orders VALUES (1, 'new'), (2, 'paid')")
            for name in FAMILY:
                await cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{name} (id INT PRIMARY KEY)"
                )
            for _ in range(3):
                await cur.execute(f"SELECT * FROM {SCHEMA}.orders WHERE status = '{SECRET}'")
                await cur.fetchall()
    finally:
        conn.close()
    return mysql_config("MONITOR")


async def test_mysql_slow_queries_are_normalized() -> None:
    db = await _mysql_setup()
    # Start from clean statistics so earlier runs cannot push this statement out of the top 20.
    conn = await _mysql_admin()
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "TRUNCATE TABLE performance_schema.events_statements_summary_by_digest"
            )
            for _ in range(3):
                await cur.execute(f"SELECT * FROM {SCHEMA}.orders WHERE status = '{SECRET}'")
                await cur.fetchall()
    finally:
        conn.close()
    data = await collect("slow_queries", db)
    assert data["available"] is True and data["since"]
    mine = [
        q
        for q in data["queries"]
        if q["text"].startswith("SELECT") and SCHEMA in q["text"] and "orders" in q["text"]
    ]
    assert mine, "the test statement is listed"
    q = mine[0]
    assert "?" in q["text"] and q["calls"] >= 3 and q["total_ms"] >= 0
    assert q["rows_examined"] is not None and q["no_index_used"] is not None
    text = json.dumps(data)
    assert SECRET not in text, "literal values never leave the database"
    assert "information_schema" not in text and "performance_schema" not in text
    assert len(data["queries"]) <= 20 and data["total_statements"] >= len(data["queries"])


async def test_mysql_locks_show_who_waits_for_whom(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await _mysql_setup()
    holder, waiter = await _mysql_admin(), await _mysql_admin()
    try:
        async with holder.cursor() as h, waiter.cursor() as w:
            await h.execute("SELECT CONNECTION_ID()")
            (holder_id,) = await h.fetchone()
            await w.execute("SELECT CONNECTION_ID()")
            (waiter_id,) = await w.fetchone()
            await holder.begin()
            await h.execute(f"UPDATE {SCHEMA}.orders SET status = '{SECRET}' WHERE id = 1")
            await waiter.begin()
            await w.execute("SET SESSION innodb_lock_wait_timeout = 30")
            blocked = asyncio.create_task(
                w.execute(f"UPDATE {SCHEMA}.orders SET status = 'other' WHERE id = 1")
            )
            await asyncio.sleep(1.5)

            monkeypatch.setattr(mysql, "LONG_TRANSACTION_SECONDS", 0)
            data = await collect("locks", db)
            await holder.rollback()
            await blocked
            await waiter.rollback()
    finally:
        holder.close()
        waiter.close()

    assert data["available"] is True and data["long_transaction_seconds"] == 0
    wait = next(x for x in data["waits"] if x["table"] == "orders")
    assert (wait["waiting_session"], wait["blocking_session"]) == (waiter_id, holder_id)
    assert wait["schema"] == SCHEMA and wait["wait_seconds"] >= 1
    assert holder_id in {t["session"] for t in data["long_transactions"]}
    assert SECRET not in json.dumps(data), "statements are never read"


async def test_mysql_table_index_lists_every_table() -> None:
    db = await _mysql_setup()
    data = await collect("table_index", db)
    schema = next(s for s in data["schemas"] if s["name"] == SCHEMA)
    names = {t[0] for t in schema["tables"]}
    assert set(FAMILY) | {"orders"} <= names
    assert data["listed_tables"] == data["total_tables"] and data["truncated"] is False
    assert all(s["name"] not in ("mysql", "sys") for s in data["schemas"])


# ---- PostgreSQL --------------------------------------------------------------------------------


async def _pg_admin() -> asyncpg.Connection:
    admin = pg_config("ADMIN")
    return await asyncpg.connect(
        host=admin.host,
        port=admin.effective_port,
        user=admin.user,
        password=admin.resolve_password(),
        database=admin.database,
        ssl=False,
    )


async def _pg_setup() -> DatabaseConfig:
    conn = await _pg_admin()
    try:
        await conn.execute(
            f"""
            create schema if not exists {SCHEMA};
            create table if not exists {SCHEMA}.orders (id int primary key, status text);
            insert into {SCHEMA}.orders values (1, 'new'), (2, 'paid') on conflict do nothing;
            """
            + "".join(
                f"create table if not exists {SCHEMA}.{n} (id int primary key);" for n in FAMILY
            )
        )
        for _ in range(3):
            await conn.fetch(f"select * from {SCHEMA}.orders where status = '{SECRET}'")
    finally:
        await conn.close()
    return pg_config("MONITOR")


async def test_postgres_without_pg_stat_statements_says_how_to_add_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = await _pg_setup()
    monkeypatch.setattr(postgres, "_PGSS_SCHEMA_SQL", "select null::text")  # as if not installed
    data = await collect("slow_queries", db)
    assert data == {"available": False, "reason": postgres.PGSS_MISSING, **_datasource(db)}


async def test_postgres_slow_queries_are_normalized() -> None:
    db = await _pg_setup()
    data = await collect("slow_queries", db)
    if not data["available"] and not os.environ.get("TEST_PG_STATEMENTS"):
        pytest.skip("pg_stat_statements is not set up here (CI sets TEST_PG_STATEMENTS=1)")
    assert data["available"] is True, data
    # Start from clean statistics so earlier runs cannot push this statement out of the top 20.
    admin = await _pg_admin()
    try:
        await admin.execute("select pg_stat_statements_reset()")
        for _ in range(3):
            await admin.fetch(f"select * from {SCHEMA}.orders where status = '{SECRET}'")
    finally:
        await admin.close()
    data = await collect("slow_queries", db)
    mine = [q for q in data["queries"] if q["text"].startswith(f"select * from {SCHEMA}.orders")]
    assert mine and "$1" in mine[0]["text"] and mine[0]["calls"] >= 3
    text = json.dumps(data)
    assert SECRET not in text
    assert "pg_catalog" not in text and "pg_stat_activity" not in text


async def test_postgres_locks_show_who_waits_for_whom(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await _pg_setup()
    holder, waiter = await _pg_admin(), await _pg_admin()
    try:
        holder_id = holder.get_server_pid()
        waiter_id = waiter.get_server_pid()
        await holder.execute("begin")
        await holder.execute(f"update {SCHEMA}.orders set status = '{SECRET}' where id = 1")
        await waiter.execute("begin; set local lock_timeout = '30s'")
        blocked = asyncio.create_task(
            waiter.execute(f"update {SCHEMA}.orders set status = 'other' where id = 1")
        )
        await asyncio.sleep(1.5)

        monkeypatch.setattr(postgres, "LONG_TRANSACTION_SECONDS", 0)
        data = await collect("locks", db)
        await holder.execute("rollback")
        await blocked
        await waiter.execute("rollback")
    finally:
        await holder.close()
        await waiter.close()

    wait = next(x for x in data["waits"] if x["waiting_session"] == waiter_id)
    assert wait["blocking_session"] == holder_id
    assert wait["blocker_state"] == "idle in transaction" and wait["wait_seconds"] >= 1
    assert holder_id in {t["session"] for t in data["long_transactions"]}
    assert SECRET not in json.dumps(data), "statements are never read"


async def test_postgres_table_index_lists_every_table() -> None:
    db = await _pg_setup()
    data = await collect("table_index", db)
    schema = next(s for s in data["schemas"] if s["name"] == SCHEMA)
    assert set(FAMILY) | {"orders"} <= {t[0] for t in schema["tables"]}
    assert all(not s["name"].startswith("pg_") for s in data["schemas"])


def _datasource(db: DatabaseConfig) -> dict[str, Any]:
    return {"format": 1, "datasource": db.name, "engine": db.engine}
