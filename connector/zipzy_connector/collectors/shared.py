"""Limits and small helpers shared by the MySQL and PostgreSQL collectors."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_QUERIES = 20  # slowest statements listed
MAX_QUERY_TEXT = 2000  # characters kept of one normalized statement
MAX_LOCK_ROWS = 50  # lock waits and long transactions listed
LONG_TRANSACTION_SECONDS = 60  # a transaction open longer than this is reported
MAX_TABLE_INDEX = 50_000  # tables listed by table_index, biggest first
# table_index stops adding tables before its answer reaches this size, so it always fits in one
# message to ZipZy (the link allows 4 MiB) whatever the table names are.
MAX_TABLE_INDEX_BYTES = 3_000_000


def unavailable(reason: str) -> dict[str, Any]:
    """The server cannot answer this collector (feature off, too old); not an error."""
    return {"available": False, "reason": reason}


def clip_text(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_QUERY_TEXT else text[: MAX_QUERY_TEXT - 1] + "…"


def since_uptime(uptime_seconds: int | None) -> str | None:
    if uptime_seconds is None:
        return None
    started = datetime.now(UTC) - timedelta(seconds=uptime_seconds)
    return started.isoformat(timespec="seconds")


def build_table_index(
    total: int, rows: Iterable[tuple[str, str, int | None, int | None]]
) -> dict[str, Any]:
    """Group [name, rows, bytes] lists by schema, within the count and size limits."""
    schemas: dict[str, list[list[Any]]] = {}
    listed = 0
    size = 0
    for schema, name, n_rows, n_bytes in rows:
        entry = [name, n_rows, n_bytes]
        # Measured as the message is encoded (json.dumps), plus the ", " before the entry.
        cost = (
            len(json.dumps(entry)) + 2 + (0 if schema in schemas else len(json.dumps(schema)) + 40)
        )
        if listed >= MAX_TABLE_INDEX or size + cost > MAX_TABLE_INDEX_BYTES:
            break
        schemas.setdefault(schema, []).append(entry)
        listed += 1
        size += cost
    return {
        "available": True,
        "reason": None,
        "total_tables": max(total, listed),
        "listed_tables": listed,
        "truncated": max(total, listed) > listed,
        "schemas": [{"name": name, "tables": tables} for name, tables in schemas.items()],
    }
