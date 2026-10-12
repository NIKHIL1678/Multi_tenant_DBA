"""PostgreSQL probe."""

import ssl as ssl_lib
from typing import Any

import asyncpg

from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.base import (
    CONNECT_TIMEOUT_S,
    MAX_CATALOG_ENTRIES,
    ProbeResult,
    catalog_of,
    guarded,
)

_CAPABILITIES_SQL = """
select
  current_setting('server_version') as version,
  exists (select 1 from pg_extension where extname = 'pg_stat_statements') as pg_stat_statements,
  (select rolsuper from pg_roles where rolname = current_user) as superuser,
  pg_has_role(current_user, 'pg_monitor', 'member') as pg_monitor,
  current_setting('transaction_read_only') = 'on' as session_read_only
"""

# Every database on the server. Sizes need CONNECT on it or pg_read_all_stats (in pg_monitor).
# Table counts are known only for the database the connector logs in to.
_CATALOG_SQL = r"""
select
  d.datname as name,
  case when has_database_privilege(d.oid, 'CONNECT')
         or pg_has_role(current_user, 'pg_read_all_stats', 'member')
       then pg_database_size(d.oid) end as size_bytes,
  case when d.datname = current_database() then (
    select count(*) from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where c.relkind in ('r', 'p')
      and n.nspname not in ('pg_catalog', 'information_schema')
      and n.nspname not like 'pg\_toast%'
  ) end as tables
from pg_database d
where not d.datistemplate and d.datallowconn
order by size_bytes desc nulls last, name
limit $1
"""


def _ssl(mode: str) -> Any:
    if mode == "disable":
        return False
    if mode == "verify-full":
        return ssl_lib.create_default_context()
    return mode  # asyncpg understands "prefer" and "require"


async def probe_postgres(db: DatabaseConfig) -> ProbeResult:
    async def run(password: str) -> ProbeResult:
        conn = await asyncpg.connect(
            host=db.host,
            port=db.effective_port,
            user=db.user,
            password=password,
            database=db.database,
            ssl=_ssl(db.tls),
            timeout=CONNECT_TIMEOUT_S,
            # Every statement in this session is read-only, whatever the user's rights are.
            server_settings={
                "application_name": "zipzy-connector",
                "default_transaction_read_only": "on",
                "statement_timeout": "5000",
            },
        )
        catalog: dict[str, Any] | None = None
        try:
            row = await conn.fetchrow(_CAPABILITIES_SQL)
            try:
                rows = await conn.fetch(_CATALOG_SQL, MAX_CATALOG_ENTRIES + 1)
                catalog = catalog_of(
                    [
                        (
                            str(r["name"]),
                            None if r["size_bytes"] is None else int(r["size_bytes"]),
                            None if r["tables"] is None else int(r["tables"]),
                        )
                        for r in rows
                    ]
                )
            except asyncpg.PostgresError:
                catalog = None  # the probe itself still counts; only the list is missing
        finally:
            await conn.close()
        return ProbeResult(
            name=db.name,
            engine="postgres",
            reachable=True,
            version=str(row["version"]).split(" ")[0],
            capabilities={
                "pg_stat_statements": bool(row["pg_stat_statements"]),
                "pg_monitor": bool(row["pg_monitor"]),
                # A superuser can do anything: ZipZy will recommend a least-privilege user.
                "least_privilege": not bool(row["superuser"]),
                "session_read_only": bool(row["session_read_only"]),
                "list_databases": True,  # pg_database is readable by every user
                "table_metadata": True,  # so is pg_class (structure only, never rows)
            },
            environment=db.environment,
            catalog=catalog,
        )

    return await guarded(db, run)
