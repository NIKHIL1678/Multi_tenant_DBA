"""Collectors against real databases, as the monitoring user, plus the pure analysis rules."""

import warnings
from typing import Any

import aiomysql
import asyncpg
import pytest

from tests.conftest import mysql_config, pg_config
from zipzy_connector.collectors import CollectorError, collect
from zipzy_connector.collectors.analysis import (
    duplicate_indexes,
    unindexed_foreign_keys,
    unused_indexes,
)
from zipzy_connector.config import ConnectorFile, DatabaseConfig
from zipzy_connector.tools import ToolError, run_tool

SCHEMA = "zipzy_collect_test"


def ix(name: str, columns: list[str], **kw: Any) -> dict[str, Any]:
    return {
        "schema": "s",
        "table": "t",
        "name": name,
        "columns": columns,
        "unique": kw.get("unique", False),
        "primary": kw.get("primary", False),
        "size_bytes": kw.get("size_bytes"),
        "scans": kw.get("scans"),
        "valid": True,
        "partial": False,
        "expression": False,
    }


# ---- pure rules --------------------------------------------------------------------------------


def test_duplicate_rules() -> None:
    found = duplicate_indexes(
        [
            ix("pk", ["id"], primary=True, unique=True),
            ix("by_status", ["status"]),
            ix("by_status_date", ["status", "created_at"]),
            ix("twin_a", ["email"]),
            ix("twin_b", ["email"]),
            ix("uniq_code", ["code"], unique=True),
            ix("code_name", ["code", "name"]),
            ix("again_id", ["id"]),
        ]
    )
    pairs = {(f["index"], f["covered_by"]) for f in found}
    assert ("by_status", "by_status_date") in pairs
    assert ("twin_b", "twin_a") in pairs and ("twin_a", "twin_b") not in pairs
    assert ("again_id", "pk") in pairs
    assert all(f["index"] != "uniq_code" for f in found), "unique rules are kept"
    assert all(f["index"] != "pk" for f in found)


def test_unused_rules_keep_rule_enforcing_indexes() -> None:
    found = unused_indexes(
        [
            ix("pk", ["id"], primary=True, unique=True, scans=0),
            ix("uniq", ["email"], unique=True, scans=0),
            ix("big", ["a"], scans=0, size_bytes=900),
            ix("small", ["b"], scans=0, size_bytes=10),
            ix("used", ["c"], scans=5),
            ix("unknown", ["d"], scans=None),
        ]
    )
    assert [f["index"] for f in found] == ["big", "small"]


def test_foreign_key_needs_a_leading_index() -> None:
    fks = [
        {"schema": "s", "table": "t", "name": "fk_a", "columns": ["a"], "references": "s.p"},
        {"schema": "s", "table": "t", "name": "fk_bc", "columns": ["b", "c"], "references": "s.q"},
        {"schema": "s", "table": "t", "name": "fk_d", "columns": ["d"], "references": "s.r"},
    ]
    found = unindexed_foreign_keys(
        fks, [ix("a_x", ["a", "x"]), ix("cb", ["c", "b"]), ix("xd", ["x", "d"])]
    )
    assert [f["constraint"] for f in found] == ["fk_d"]


# ---- real databases ----------------------------------------------------------------------------


async def _pg_fixture() -> DatabaseConfig:
    admin = pg_config("ADMIN")
    conn = await asyncpg.connect(
        host=admin.host,
        port=admin.effective_port,
        user=admin.user,
        password=admin.resolve_password(),
        database=admin.database,
        ssl=False,
    )
    try:
        await conn.execute(
            f"""
            create schema if not exists {SCHEMA};
            create table if not exists {SCHEMA}.customers (id int primary key, email text);
            create table if not exists {SCHEMA}.orders (
              id int primary key,
              customer_id int references {SCHEMA}.customers (id),
              status text, created_at date);
            create index if not exists orders_status on {SCHEMA}.orders (status);
            create index if not exists orders_status_date on {SCHEMA}.orders (status, created_at);
            create table if not exists {SCHEMA}.audit_log (at timestamptz, note text);
            """
        )
    finally:
        await conn.close()
    return pg_config("MONITOR")


async def _mysql_fixture() -> DatabaseConfig:
    admin = mysql_config("ADMIN")
    conn = await aiomysql.connect(
        host=admin.host,
        port=admin.effective_port,
        user=admin.user,
        password=admin.resolve_password(),
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            warnings.simplefilter("ignore")  # "already exists" notes on a second run
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {SCHEMA}")
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.orders (id INT PRIMARY KEY,"
                " status VARCHAR(20), created_at DATE,"
                " KEY by_status (status), KEY by_status_date (status, created_at))"
            )
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA}.audit_log (at DATETIME, note TEXT)"
            )
    finally:
        conn.close()
    return mysql_config("MONITOR")


def _common_shape(data: dict[str, Any], name: str) -> None:
    assert data["format"] == 1 and data["datasource"] == name


async def test_postgres_collectors() -> None:
    db = await _pg_fixture()

    health = await collect("health", db)
    _common_shape(health, db.name)
    assert health["connections"]["max"] > 0 and health["connections"]["current"] >= 1
    assert 0 <= health["cache_hit_ratio"] <= 1
    assert health["replication"]["is_replica"] is False
    assert "shared_buffers" in health["settings"]

    tables = await collect("table_stats", db)
    by_name = {(t["schema"], t["name"]): t for t in tables["tables"]}
    assert by_name[(SCHEMA, "orders")]["has_primary_key"] is True
    assert by_name[(SCHEMA, "audit_log")]["has_primary_key"] is False
    assert tables["total_tables"] >= 3

    indexes = await collect("indexes", db)
    assert indexes["usage_since"]
    dupes = {(d["index"], d["covered_by"]) for d in indexes["duplicates"]}
    assert ("orders_status", "orders_status_date") in dupes
    fks = [f for f in indexes["unindexed_foreign_keys"] if f["schema"] == SCHEMA]
    assert [(f["table"], f["columns"]) for f in fks] == [("orders", ["customer_id"])]
    assert (SCHEMA, "audit_log") in {
        (m["schema"], m["table"]) for m in indexes["missing_primary_keys"]
    }
    assert any(i["size_bytes"] for i in indexes["indexes"])


async def test_mysql_collectors() -> None:
    db = await _mysql_fixture()

    health = await collect("health", db)
    _common_shape(health, db.name)
    assert health["connections"]["max"] > 0
    assert health["throughput_unit"] == "queries"
    assert "max_connections" in health["settings"]

    tables = await collect("table_stats", db)
    by_name = {(t["schema"], t["name"]): t for t in tables["tables"]}
    assert by_name[(SCHEMA, "audit_log")]["has_primary_key"] is False
    assert by_name[(SCHEMA, "orders")]["engine"] == "InnoDB"

    indexes = await collect("indexes", db)
    dupes = {(d["schema"], d["index"], d["covered_by"]) for d in indexes["duplicates"]}
    assert (SCHEMA, "by_status", "by_status_date") in dupes
    assert (SCHEMA, "audit_log") in {
        (m["schema"], m["table"]) for m in indexes["missing_primary_keys"]
    }
    orders = [i for i in indexes["indexes"] if i["schema"] == SCHEMA and i["table"] == "orders"]
    assert {i["name"] for i in orders} == {"PRIMARY", "by_status", "by_status_date"}


async def test_collectors_never_leak_the_password() -> None:
    db = pg_config("MONITOR", password="wrong-secret-xyz")
    with pytest.raises(CollectorError) as info:
        await collect("health", db)
    assert info.value.code == "collector_failed"
    assert "wrong-secret-xyz" not in info.value.message


async def test_tools_are_allow_listed_and_scoped() -> None:
    config = ConnectorFile.model_validate(
        {
            "databases": [
                {
                    "name": "down",
                    "engine": "mysql",
                    "host": "127.0.0.1",
                    "port": 1,
                    "user": "u",
                    "password": "p",
                    "tls": "disable",
                }
            ]
        }
    )
    with pytest.raises(ToolError) as info:
        await run_tool(config, "indexes", {"datasource": "down"})
    assert info.value.code == "collector_failed"
    with pytest.raises(ToolError) as info:
        await run_tool(config, "table_stats", {"datasource": "someone-elses"})
    assert info.value.code == "unknown_datasource"
    with pytest.raises(ToolError) as info:
        await run_tool(config, "run_sql", {"sql": "select 1"})
    assert info.value.code == "unknown_tool"
