"""Facts: the numbered pieces of evidence the agents read and must cite.

Every number a specialist sees comes from a collector snapshot and gets an id: H (health),
L (locks), T (tables), I (indexes), Q (statements). A finding lists the ids it relies on; the
Verifier drops any finding that cites nothing real. Each fact also has a short `summary` that
the dashboard shows when someone points at the evidence chip.

Only statistics, structure and normalized statement text are here, never table rows. Names come
from the customer's database: they are data, never instructions.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.schemas.snapshots import (
    HealthData,
    IndexesData,
    LocksData,
    SlowQueriesData,
    TableStatsData,
)

MAX_TABLES = 25
MAX_INDEX_FACTS = 40
MAX_QUERIES = 20

# MySQL digests print some keywords used as column names as SQL_TSI_<NAME> (`day` -> SQL_TSI_DAY).
_TSI = re.compile(r"\bSQL_TSI_([A-Z_]+)\b")
_WORD = re.compile(r"`([^`]+)`|\"([^\"]+)\"|\b([A-Za-z_][A-Za-z0-9_$]*)\b")


def qualified(schema: str, name: str) -> str:
    return f"{schema}.{name}"


def readable_statement(text: str) -> str:
    """MySQL digest text with SQL_TSI_DAY shown as `day` again, as the column is named."""
    return _TSI.sub(lambda m: f"`{m.group(1).lower()}`", text)


def statement_words(text: str) -> set[str]:
    """Identifiers a statement mentions (lower case), to check columns an index would use."""
    words: set[str] = set()
    for quoted_bt, quoted_dq, bare in _WORD.findall(readable_statement(text)):
        words.add((quoted_bt or quoted_dq or bare).lower())
    return words


def _size(n: int | None) -> str:
    if n is None:
        return "size unknown"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _count(n: int | None) -> str:
    return "unknown" if n is None else f"{n:,}"


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    summary: str  # one line for people
    data: dict[str, Any]  # what the model reads


@dataclass(slots=True)
class Evidence:
    """Facts for one run plus what is known to exist (for the Verifier)."""

    facts: dict[str, Fact] = field(default_factory=dict)
    tables: set[str] = field(default_factory=set)  # "schema.table", lower case
    indexes: dict[str, set[str]] = field(default_factory=dict)  # table -> index names (lower)
    columns: dict[str, set[str]] = field(default_factory=dict)  # table -> known column names
    notes: list[str] = field(default_factory=list)  # what could not be looked at, and why

    def add(self, prefix: str, summary: str, data: dict[str, Any]) -> Fact:
        n = sum(1 for k in self.facts if k.startswith(prefix)) + 1
        fact = Fact(f"{prefix}{n}", summary, data)
        self.facts[fact.id] = fact
        return fact

    def for_model(self, prefixes: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = tuple(prefixes)
        return {k: f.data for k, f in self.facts.items() if k.startswith(wanted)}

    def know_table(self, schema: str, name: str) -> str:
        key = qualified(schema, name).lower()
        self.tables.add(key)
        return key

    def know_index(self, schema: str, table: str, index: str, columns: Iterable[str]) -> None:
        key = self.know_table(schema, table)
        self.indexes.setdefault(key, set()).add(index.lower())
        self.columns.setdefault(key, set()).update(c.lower() for c in columns)


def age_note(what: str, collected_at: datetime, now: datetime | None = None) -> str | None:
    minutes = int(((now or datetime.now(UTC)) - collected_at).total_seconds() // 60)
    return f"{what}: collected {minutes} minutes ago." if minutes >= 10 else None


# ---- builders --------------------------------------------------------------------------------


def add_health(ev: Evidence, h: HealthData) -> None:
    c = h.connections
    if c.current is not None:
        used = f"{c.current} of {c.max}" if c.max else f"{c.current}"
        ev.add(
            "H",
            f"Connections: {used} in use, {c.active if c.active is not None else '?'} running",
            {"connections": c.model_dump(mode="json")},
        )
    if h.cache_hit_ratio is not None:
        ev.add(
            "H",
            f"Cache hit rate {h.cache_hit_ratio:.1%}",
            {"cache_hit_ratio": round(h.cache_hit_ratio, 4)},
        )
    if h.throughput_per_second is not None:
        ev.add(
            "H",
            f"{h.throughput_per_second:.1f} {h.throughput_unit}/s since start",
            {"throughput_per_second": h.throughput_per_second, "unit": h.throughput_unit},
        )
    if h.uptime_seconds is not None:
        ev.add("H", f"Up {h.uptime_seconds // 3600} h", {"uptime_seconds": h.uptime_seconds})
    if h.deadlocks:
        ev.add("H", f"{h.deadlocks:,} deadlocks since start", {"deadlocks": h.deadlocks})
    if h.temp_tables_on_disk_ratio is not None:
        ev.add(
            "H",
            f"{h.temp_tables_on_disk_ratio:.0%} of temporary tables went to disk",
            {"temp_tables_on_disk_ratio": round(h.temp_tables_on_disk_ratio, 4)},
        )
    if h.replication.is_replica:
        ev.add(
            "H",
            f"Replica, {h.replication.lag_seconds or 0:.0f} s behind",
            {"replication": h.replication.model_dump(mode="json")},
        )
    if h.settings:
        ev.add("H", "Server settings", {"settings": dict(sorted(h.settings.items()))})


def add_locks(ev: Evidence, data: LocksData) -> None:
    if not data.available:
        ev.notes.append(f"Locks could not be read: {data.reason}")
        return
    for w in data.waits[:20]:
        where = qualified(w.schema_name, w.table) if w.schema_name and w.table else "a table"
        if w.schema_name and w.table:
            ev.know_table(w.schema_name, w.table)
        ev.add(
            "L",
            f"Session {w.waiting_session} waited {w.wait_seconds} s for {w.blocking_session} "
            f"on {where}",
            {"lock_wait": w.model_dump(mode="json")},
        )
    for t in data.long_transactions[:10]:
        ev.add(
            "L",
            f"Session {t.session} has had a transaction open for {t.seconds} s ({t.state})",
            {"long_transaction": t.model_dump(mode="json")},
        )
    if not data.waits and not data.long_transactions:
        ev.add("L", "No lock waits or long transactions", {"lock_waits": 0})


def add_tables(ev: Evidence, data: TableStatsData, focus: set[str]) -> None:
    for t in data.tables:
        ev.know_table(t.schema_name, t.name)
    chosen = sorted(
        data.tables,
        key=lambda t: (
            qualified(t.schema_name, t.name).lower() not in focus,
            -((t.data_bytes or 0) + (t.index_bytes or 0)),
        ),
    )[:MAX_TABLES]
    for t in chosen:
        name = qualified(t.schema_name, t.name)
        size = (t.data_bytes or 0) + (t.index_bytes or 0)
        bits = [f"{_count(t.rows)} rows", _size(size)]
        if not t.has_primary_key:
            bits.append("no primary key")
        if t.seq_scans:
            bits.append(f"{t.seq_scans:,} full scans")
        ev.add("T", f"{name}: {', '.join(bits)}", {"table": t.model_dump(mode="json")})
    if data.truncated:
        ev.notes.append(f"Only the biggest of {data.total_tables:,} tables have statistics.")


def add_indexes(ev: Evidence, data: IndexesData, focus: set[str]) -> None:
    for i in data.indexes:
        ev.know_index(i.schema_name, i.table, i.name, i.columns)

    def table_of(schema: str, table: str) -> str:
        return qualified(schema, table)

    problems: list[tuple[str, dict[str, Any]]] = []
    for u in data.unused:
        problems.append(
            (
                f"Index {u.index} on {table_of(u.schema_name, u.table)} unused "
                f"({_size(u.size_bytes)})",
                {"unused_index": u.model_dump(mode="json")},
            )
        )
    for d in data.duplicates:
        problems.append(
            (
                f"Index {d.index} on {table_of(d.schema_name, d.table)} is covered by "
                f"{d.covered_by}",
                {"duplicate_index": d.model_dump(mode="json")},
            )
        )
    for f in data.unindexed_foreign_keys:
        problems.append(
            (
                f"Foreign key {f.constraint} on {table_of(f.schema_name, f.table)} "
                f"({', '.join(f.columns)}) has no index",
                {"unindexed_foreign_key": f.model_dump(mode="json")},
            )
        )
    for m in data.missing_primary_keys:
        ev.know_table(m.schema_name, m.table)
        problems.append(
            (
                f"{table_of(m.schema_name, m.table)} has no primary key ({_count(m.rows)} rows)",
                {"missing_primary_key": m.model_dump(mode="json")},
            )
        )
    for s in data.full_scans:
        ev.know_table(s.schema_name, s.table)
        scans = s.full_scans if s.full_scans is not None else s.rows_read_without_index
        problems.append(
            (
                f"{table_of(s.schema_name, s.table)} read in full often ({_count(scans)})",
                {"full_scan": s.model_dump(mode="json")},
            )
        )
    for v in data.invalid:
        problems.append(
            (
                f"Index {v.index} on {table_of(v.schema_name, v.table)} is invalid",
                {"invalid_index": v.model_dump(mode="json")},
            )
        )

    # Problems first (focus tables first), then the definitions of indexes on focus tables so
    # the model knows what already exists before it suggests a new one.
    def in_focus(item: tuple[str, dict[str, Any]]) -> bool:
        row = next(iter(item[1].values()))
        return qualified(row["schema"], row["table"]).lower() in focus

    problems.sort(key=lambda p: not in_focus(p))
    existing = [
        (
            f"{qualified(i.schema_name, i.table)} has index {i.name} ({', '.join(i.columns)})",
            {"index": i.model_dump(mode="json")},
        )
        for i in data.indexes
        if qualified(i.schema_name, i.table).lower() in focus
    ]
    for summary, payload in (problems + existing)[:MAX_INDEX_FACTS]:
        ev.add("I", summary, payload)
    if data.usage_since:
        ev.notes.append(f"Index usage is counted since {data.usage_since:%d %b %Y}.")


def add_queries(ev: Evidence, data: SlowQueriesData, focus: set[str]) -> None:
    if not data.available:
        ev.notes.append(f"Slow statements could not be read: {data.reason}")
        return
    focus_names = {f.split(".", 1)[-1] for f in focus}

    def mentions_focus(text: str) -> bool:
        return bool(focus_names & statement_words(text))

    chosen = sorted(data.queries, key=lambda q: (not mentions_focus(q.text), -q.total_ms))
    for q in chosen[:MAX_QUERIES]:
        text = readable_statement(q.text)
        per_run = round(q.rows_examined / q.calls) if q.rows_examined and q.calls else None
        bits = [f"{q.calls:,} runs", f"{q.mean_ms:,.0f} ms average"]
        if per_run is not None:
            bits.append(f"{per_run:,} rows read per run")
        if q.no_index_used:
            bits.append("no index used")
        payload = q.model_dump(mode="json")
        payload["text"] = text
        payload["rows_read_per_run"] = per_run
        ev.add("Q", f"{text[:80]}{'…' if len(text) > 80 else ''} — {', '.join(bits)}", payload)
