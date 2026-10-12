"""Collectors: fixed, read-only questions the connector can answer about one database.

    health        is the server OK right now?          (connections, cache, replication)
    table_stats   which tables are big or growing?     (rows, sizes, scans, primary keys)
    indexes       which indexes are unused, duplicated or missing?

Each runs in a read-only session with a 5 s limit per statement and a 30 s limit overall,
returns at most a few hundred items, and never reads table rows. Adding one = a function per
engine + one line in COLLECTORS + the name on both allow-lists (here and in ZipZy).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from zipzy_connector.collectors import mysql, postgres
from zipzy_connector.config import ConfigError, DatabaseConfig
from zipzy_connector.engines.base import describe_error

COLLECT_TIMEOUT_S = 30
FORMAT_VERSION = 1  # bumped when a collector's output changes shape

Collector = Callable[[DatabaseConfig, str], Awaitable[dict[str, Any]]]

COLLECTORS: dict[str, dict[str, Collector]] = {
    "health": {"postgres": postgres.health, "mysql": mysql.health, "mariadb": mysql.health},
    "table_stats": {
        "postgres": postgres.table_stats,
        "mysql": mysql.table_stats,
        "mariadb": mysql.table_stats,
    },
    "indexes": {"postgres": postgres.indexes, "mysql": mysql.indexes, "mariadb": mysql.indexes},
}


class CollectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def collect(name: str, db: DatabaseConfig) -> dict[str, Any]:
    by_engine = COLLECTORS.get(name)
    if by_engine is None or db.engine not in by_engine:
        raise CollectorError("unsupported", f"'{name}' is not available for {db.engine}")
    try:
        password = db.resolve_password()
    except ConfigError as exc:
        raise CollectorError("config", str(exc)) from None
    try:
        data = await asyncio.wait_for(by_engine[db.engine](db, password), COLLECT_TIMEOUT_S)
    except TimeoutError:
        raise CollectorError("timeout", f"no answer within {COLLECT_TIMEOUT_S}s") from None
    except Exception as exc:  # driver errors become a short, password-free reason
        raise CollectorError("collector_failed", describe_error(exc, password)) from None
    return {"format": FORMAT_VERSION, "datasource": db.name, "engine": db.engine, **data}


__all__ = ["COLLECTORS", "CollectorError", "collect"]
