"""PostgreSQL probe."""

import ssl as ssl_lib
from typing import Any

import asyncpg

from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.base import CONNECT_TIMEOUT_S, ProbeResult, guarded

_CAPABILITIES_SQL = """
select
  current_setting('server_version') as version,
  exists (select 1 from pg_extension where extname = 'pg_stat_statements') as pg_stat_statements,
  (select rolsuper from pg_roles where rolname = current_user) as superuser,
  pg_has_role(current_user, 'pg_monitor', 'member') as pg_monitor,
  current_setting('transaction_read_only') = 'on' as session_read_only
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
        try:
            row = await conn.fetchrow(_CAPABILITIES_SQL)
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
            },
            environment=db.environment,
        )

    return await guarded(db, run)
