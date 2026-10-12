"""Probes against real databases, logged in as the users a customer would create."""

import warnings

import aiomysql
import asyncpg

from tests.conftest import mysql_config, pg_config
from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines import probe
from zipzy_connector.engines.base import MAX_CATALOG_ENTRIES, catalog_of
from zipzy_connector.engines.mysql import global_privileges

CATALOG_SCHEMA = "zipzy_catalog_test"


async def _pg_admin_table() -> None:
    """As the admin: make sure the test database has at least one table."""
    cfg = pg_config("ADMIN")
    conn = await asyncpg.connect(
        host=cfg.host,
        port=cfg.effective_port,
        user=cfg.user,
        password=cfg.resolve_password(),
        database=cfg.database,
        ssl=False,
    )
    try:
        await conn.execute("create table if not exists catalog_probe_t (id int primary key)")
    finally:
        await conn.close()


async def _mysql_admin_schema() -> None:
    """As the admin: a schema with a table and a secret row the monitor must never read."""
    cfg = mysql_config("ADMIN")
    conn = await aiomysql.connect(
        host=cfg.host,
        port=cfg.effective_port,
        user=cfg.user,
        password=cfg.resolve_password(),
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            warnings.simplefilter("ignore")  # "already exists" notes on a second run
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {CATALOG_SCHEMA}")
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {CATALOG_SCHEMA}.salaries "
                "(id INT PRIMARY KEY, amount INT, KEY idx_amount (amount))"
            )
            await cur.execute("INSERT IGNORE INTO zipzy_catalog_test.salaries VALUES (1, 99)")
    finally:
        conn.close()


async def test_postgres_monitor_user() -> None:
    r = await probe(pg_config("MONITOR", environment="production"))
    assert r.reachable, r.error
    assert r.engine == "postgres" and r.version and r.version[0].isdigit()
    assert r.capabilities["least_privilege"] is True
    assert r.capabilities["pg_monitor"] is True
    assert r.capabilities["session_read_only"] is True
    assert r.report()["environment"] == "production"


async def test_postgres_catalog_lists_every_database() -> None:
    await _pg_admin_table()
    cfg = pg_config("MONITOR")
    r = await probe(cfg)
    assert r.reachable, r.error
    assert r.capabilities["list_databases"] is True
    assert r.catalog is not None and r.catalog["truncated"] is False
    by_name = {d["name"]: d for d in r.catalog["databases"]}
    own = by_name[str(cfg.database)]
    assert own["size_bytes"] and own["size_bytes"] > 0
    assert own["tables"] and own["tables"] >= 1
    assert "template0" not in by_name and "template1" not in by_name
    others = [d for name, d in by_name.items() if name != cfg.database]
    assert all(d["tables"] is None for d in others), "only the logged-in database is counted"


async def test_postgres_superuser_is_flagged() -> None:
    r = await probe(pg_config("ADMIN"))
    assert r.reachable, r.error
    assert r.capabilities["least_privilege"] is False


async def test_postgres_wrong_password_never_leaks_it() -> None:
    r = await probe(pg_config("MONITOR", password="wrong-secret-xyz"))
    assert not r.reachable
    assert r.error and "wrong-secret-xyz" not in r.error


async def test_mysql_monitor_user() -> None:
    r = await probe(mysql_config("MONITOR"))
    assert r.reachable, r.error
    assert r.engine in ("mysql", "mariadb") and r.version
    assert r.capabilities["least_privilege"] is True
    assert r.capabilities["performance_schema"] is True


async def test_mysql_catalog_shows_structure_never_rows() -> None:
    await _mysql_admin_schema()
    r = await probe(mysql_config("MONITOR"))
    assert r.reachable, r.error
    assert r.capabilities["list_databases"] is True
    assert r.capabilities["table_metadata"] is True
    assert r.capabilities["least_privilege"] is True, "SHOW DATABASES/VIEW are not write rights"
    assert r.catalog is not None
    by_name = {d["name"]: d for d in r.catalog["databases"]}
    assert CATALOG_SCHEMA in by_name
    assert by_name[CATALOG_SCHEMA]["tables"] == 1
    assert by_name[CATALOG_SCHEMA]["size_bytes"] is not None
    for system in ("mysql", "sys", "information_schema", "performance_schema"):
        assert system not in by_name

    # The same user still cannot read the rows.
    cfg = mysql_config("MONITOR")
    conn = await aiomysql.connect(
        host=cfg.host,
        port=cfg.effective_port,
        user=cfg.user,
        password=cfg.resolve_password(),
    )
    try:
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT amount FROM zipzy_catalog_test.salaries")
                raise AssertionError("the monitoring user must not read table rows")
            except aiomysql.OperationalError as exc:
                assert exc.args[0] == 1142  # SELECT command denied
    finally:
        conn.close()


def test_mysql_global_privileges_are_parsed() -> None:
    grants = [
        "GRANT PROCESS, SHOW DATABASES, REPLICATION CLIENT, SHOW VIEW ON *.* TO `m`@`%`",
        "GRANT SELECT ON `performance_schema`.* TO `m`@`%`",
    ]
    assert global_privileges(grants) == {
        "PROCESS",
        "SHOW DATABASES",
        "REPLICATION CLIENT",
        "SHOW VIEW",
    }, "a SELECT on one schema is not a server-wide privilege"


def test_catalog_is_capped() -> None:
    rows: list[tuple[str, int | None, int | None]] = [
        (f"db{i}", i, None) for i in range(MAX_CATALOG_ENTRIES + 1)
    ]
    catalog = catalog_of(rows)
    assert len(catalog["databases"]) == MAX_CATALOG_ENTRIES
    assert catalog["truncated"] is True
    assert catalog_of(rows[:3])["truncated"] is False


async def test_mysql_admin_is_flagged() -> None:
    r = await probe(mysql_config("ADMIN"))
    assert r.reachable, r.error
    assert r.capabilities["least_privilege"] is False


async def test_mysql_wrong_password_never_leaks_it() -> None:
    r = await probe(mysql_config("MONITOR", password="wrong-secret-xyz"))
    assert not r.reachable
    assert r.error and "wrong-secret-xyz" not in r.error


async def test_unreachable_host_fails_cleanly() -> None:
    db = DatabaseConfig.model_validate(
        {
            "name": "nowhere",
            "engine": "postgres",
            "host": "127.0.0.1",
            "port": 1,  # nothing listens here
            "database": "x",
            "user": "u",
            "password": "p",
            "tls": "disable",
        }
    )
    r = await probe(db)
    assert not r.reachable and r.error
    assert r.report() == {
        "local_name": "nowhere",
        "engine": "postgres",
        "version": None,
        "reachable": False,
        "capabilities": None,
        "environment": None,
        "catalog": None,
    }


async def test_missing_password_env_is_a_reason_not_a_crash() -> None:
    db = DatabaseConfig.model_validate(
        {
            "name": "x",
            "engine": "mysql",
            "host": "h",
            "user": "u",
            "password_env": "DEFINITELY_NOT_SET_123",
        }
    )
    r = await probe(db)
    assert not r.reachable and r.error and "DEFINITELY_NOT_SET_123" in r.error
