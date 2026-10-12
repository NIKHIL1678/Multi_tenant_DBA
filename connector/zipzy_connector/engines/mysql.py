"""MySQL / MariaDB probe (same protocol; told apart by the version string)."""

import ssl as ssl_lib
from typing import Any

import aiomysql

from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.base import CONNECT_TIMEOUT_S, ProbeResult, guarded

# Privileges that let a user change data or the server. A monitoring user needs none of them.
_WRITE_PRIVILEGES = (
    "ALL PRIVILEGES",
    "SUPER",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "GRANT OPTION",
)


def _ssl(mode: str) -> ssl_lib.SSLContext | None:
    if mode in ("disable", "prefer"):
        # aiomysql has no "try TLS, fall back" mode; "prefer" behaves as plain here.
        return None
    ctx = ssl_lib.create_default_context()
    if mode == "require":
        # Encrypted but not verified: the same meaning as libpq's "require".
        ctx.check_hostname = False
        ctx.verify_mode = ssl_lib.CERT_NONE
    return ctx


async def probe_mysql(db: DatabaseConfig) -> ProbeResult:
    async def run(password: str) -> ProbeResult:
        conn = await aiomysql.connect(
            host=db.host,
            port=db.effective_port,
            user=db.user,
            password=password,
            db=db.database,
            ssl=_ssl(db.tls),
            connect_timeout=CONNECT_TIMEOUT_S,
            autocommit=True,
        )
        try:
            async with conn.cursor() as cur:
                # Every statement in this session is read-only, whatever the user's rights are.
                await cur.execute("SET SESSION TRANSACTION READ ONLY")
                await cur.execute("SELECT VERSION(), @@performance_schema")
                version_raw, perf_schema = await cur.fetchone()
                await cur.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants: list[Any] = [row[0] for row in await cur.fetchall()]
        finally:
            conn.close()

        version = str(version_raw)
        engine = "mariadb" if "mariadb" in version.lower() else "mysql"
        grant_text = " ".join(str(g).upper() for g in grants)
        writes = any(p in grant_text for p in _WRITE_PRIVILEGES)
        return ProbeResult(
            name=db.name,
            engine=engine,
            reachable=True,
            version=version.split("-")[0],
            capabilities={
                "performance_schema": bool(perf_schema),
                "least_privilege": not writes,
                "session_read_only": True,
            },
            environment=db.environment,
        )

    return await guarded(db, run)
