"""The Verifier: plain code that decides which findings and which SQL survive.

A finding is kept only if
1. it cites at least one fact that exists (facts it invents are removed);
2. the table it is about, if any, exists on the server.
A suggested statement is kept only if
3. it is exactly one statement of an allowed shape for the engine (below), with no comments
   or string literals;
4. the table exists, a new index does not already exist, an index to drop does exist and is not
   a primary key, and every column of a new index was seen in the cited evidence (an existing
   index or a statement that uses it).
Anything else is removed from the finding, which stays as advice, and the reason is noted.

Allowed shapes (everything else is refused, in particular UPDATE, DELETE, INSERT, DROP TABLE,
TRUNCATE, ALTER, GRANT, CREATE UNIQUE INDEX and multiple statements):

    MySQL / MariaDB   CREATE INDEX i ON s.t (c1, c2(10) DESC) [ALGORITHM=INPLACE] [LOCK=NONE]
                      DROP INDEX i ON s.t
                      ANALYZE TABLE s.t
                      OPTIMIZE TABLE s.t                       (rebuilds the table: risk >= medium)
    PostgreSQL        CREATE INDEX CONCURRENTLY [IF NOT EXISTS] i ON s.t [USING btree] (c1, c2)
                      DROP INDEX CONCURRENTLY [IF EXISTS] s.i
                      ANALYZE s.t
                      VACUUM (ANALYZE) s.t
                      REINDEX INDEX CONCURRENTLY s.i

The connector checks the same allow-list again before it ever runs an approved statement (5.3).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai.facts import Evidence, statement_words
from app.ai.outputs import FindingOut
from app.models.enums import DbEngine

Risk = Literal["low", "medium", "high"]
_RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

_IDENT = r'(?:`[^`\s]+`|"[^"\s]+"|[A-Za-z_][A-Za-z0-9_$]*)'
_QUAL = rf"{_IDENT}(?:\s*\.\s*{_IDENT})?"
_COL = rf"{_IDENT}(?:\s*\(\s*\d+\s*\))?(?:\s+(?:ASC|DESC))?"
_COLS = rf"\(\s*(?P<cols>{_COL}(?:\s*,\s*{_COL})*)\s*\)"

_SHAPES: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "mysql": [
        (
            "create_index",
            re.compile(
                rf"CREATE\s+INDEX\s+(?P<index>{_IDENT})\s+ON\s+(?P<table>{_QUAL})\s*{_COLS}"
                r"(?:\s+ALGORITHM\s*=\s*INPLACE)?(?:\s+LOCK\s*=\s*NONE)?",
                re.I,
            ),
        ),
        (
            "drop_index",
            re.compile(rf"DROP\s+INDEX\s+(?P<index>{_IDENT})\s+ON\s+(?P<table>{_QUAL})", re.I),
        ),
        ("analyze", re.compile(rf"ANALYZE\s+TABLE\s+(?P<table>{_QUAL})", re.I)),
        ("optimize", re.compile(rf"OPTIMIZE\s+TABLE\s+(?P<table>{_QUAL})", re.I)),
    ],
    "postgres": [
        (
            "create_index",
            re.compile(
                rf"CREATE\s+INDEX\s+CONCURRENTLY\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                rf"(?P<index>{_IDENT})\s+ON\s+(?P<table>{_QUAL})(?:\s+USING\s+btree)?\s*{_COLS}",
                re.I,
            ),
        ),
        (
            "drop_index",
            re.compile(
                rf"DROP\s+INDEX\s+CONCURRENTLY\s+(?:IF\s+EXISTS\s+)?(?P<qindex>{_QUAL})", re.I
            ),
        ),
        ("analyze", re.compile(rf"ANALYZE\s+(?P<table>{_QUAL})", re.I)),
        ("vacuum", re.compile(rf"VACUUM\s*\(\s*ANALYZE\s*\)\s*(?P<table>{_QUAL})", re.I)),
        (
            "reindex",
            re.compile(rf"REINDEX\s+INDEX\s+CONCURRENTLY\s+(?P<qindex>{_QUAL})", re.I),
        ),
    ],
}
_MIN_RISK: dict[str, Risk] = {"optimize": "medium", "drop_index": "medium"}


def _family(engine: str) -> str:
    return "postgres" if engine == DbEngine.POSTGRES else "mysql"


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in '`"':
        return name[1:-1]
    return name


_IDENT_RE = re.compile(_IDENT)


def _split(qualified_name: str) -> list[str]:
    """'`hrm`.`attendance`' -> ['hrm', 'attendance'] (the shape was already matched)."""
    return [_unquote(p) for p in _IDENT_RE.findall(qualified_name)]


def _column_name(col: str) -> str:
    col = re.sub(r"\s+(ASC|DESC)$", "", col.strip(), flags=re.I)
    col = re.sub(r"\s*\(\s*\d+\s*\)$", "", col)
    return _unquote(col).lower()


@dataclass(slots=True)
class CheckedAction:
    kind: str
    statement: str
    table: str | None  # "schema.table" lower case
    reason: str
    risk: Risk


@dataclass(slots=True)
class VerifiedFinding:
    finding: FindingOut
    evidence: list[str]
    table: str | None
    action: CheckedAction | None
    notes: list[str] = field(default_factory=list)
    specialist: str = ""  # who found it


def _resolve_table(raw: str, ev: Evidence, default_schema: str | None) -> str | None:
    parts = _split(raw)
    if len(parts) == 1:
        if default_schema is None:
            candidates = [t for t in ev.tables if t.split(".", 1)[1] == parts[0].lower()]
            return candidates[0] if len(candidates) == 1 else None
        parts = [default_schema, parts[0]]
    key = f"{parts[0]}.{parts[1]}".lower()
    return key if key in ev.tables else None


def check_statement(
    statement: str,
    engine: str,
    ev: Evidence,
    cited: list[str],
    *,
    default_schema: str | None = None,
) -> tuple[CheckedAction | None, str | None]:
    """(action, None) when allowed, (None, why not) otherwise."""
    sql = statement.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        return None, "the suggested statement was empty"
    if ";" in sql or "--" in sql or "/*" in sql or "#" in sql or "'" in sql:
        return None, "only one plain statement, without comments or text values, is allowed"

    for kind, shape in _SHAPES[_family(engine)]:
        m = shape.fullmatch(sql)
        if m is None:
            continue
        groups = m.groupdict()
        table: str | None = None
        if groups.get("table"):
            table = _resolve_table(groups["table"], ev, default_schema)
            if table is None:
                return None, f"table {groups['table']} is not on this server"

        if kind == "create_index" and table is not None:
            index = _unquote(groups["index"]).lower()
            if index in ev.indexes.get(table, set()):
                return None, f"an index named {index} already exists on {table}"
            seen = set(ev.columns.get(table, set()))
            for fact_id in cited:
                fact = ev.facts.get(fact_id)
                if fact is not None:
                    seen |= statement_words(str(fact.data))
            cols = [_column_name(c) for c in re.split(r"\s*,\s*", groups["cols"])]
            unknown = [c for c in cols if c not in seen]
            if unknown:
                return None, f"column {', '.join(unknown)} is not in the evidence"
        elif kind == "drop_index":
            if table is not None:  # MySQL: DROP INDEX i ON s.t
                index = _unquote(groups["index"]).lower()
                if index not in ev.indexes.get(table, set()):
                    return None, f"there is no index {index} on {table}"
                if index == "primary":
                    return None, "a primary key cannot be dropped"
            else:  # PostgreSQL: DROP INDEX CONCURRENTLY s.i
                found = _find_index(groups["qindex"], ev)
                if found is None:
                    return None, f"there is no index {groups['qindex']}"
                table = found
        elif kind == "reindex":
            table = _find_index(groups["qindex"], ev)
            if table is None:
                return None, f"there is no index {groups['qindex']}"
        return CheckedAction(kind, sql, table, "", "low"), None
    return None, "this kind of statement is not allowed (only index and maintenance statements)"


def _find_index(raw: str, ev: Evidence) -> str | None:
    """The table of a PostgreSQL index named schema.index (or a unique bare name)."""
    parts = [p.lower() for p in _split(raw)]
    hits = [
        table
        for table, names in ev.indexes.items()
        if parts[-1] in names and (len(parts) == 1 or table.split(".", 1)[0] == parts[0])
    ]
    return hits[0] if len(hits) == 1 else None


def verify(
    findings: list[FindingOut], engine: str, ev: Evidence
) -> tuple[list[VerifiedFinding], list[str]]:
    """Keep what is backed by evidence; strip SQL that is not allowed. Returns notes too."""
    kept: list[VerifiedFinding] = []
    notes: list[str] = []
    for f in findings:
        cited = [e for e in dict.fromkeys(f.evidence) if e in ev.facts]
        if not cited:
            notes.append(f"Left out “{f.title}”: it cited no evidence.")
            continue
        table: str | None = None
        if f.table:
            table = _resolve_table(f.table, ev, None)
            if table is None:
                notes.append(f"Left out “{f.title}”: table {f.table} is not on this server.")
                continue
        verified = VerifiedFinding(f, cited, table, None)
        if f.action is not None:
            default_schema = table.split(".", 1)[0] if table else None
            action, why = check_statement(
                f.action.statement, engine, ev, cited, default_schema=default_schema
            )
            if action is None:
                verified.notes.append(f"The suggested SQL was removed: {why}.")
            else:
                action.reason = f.action.reason
                floor = _MIN_RISK.get(action.kind, "low")
                action.risk = max(f.action.risk, floor, key=_RISK_ORDER.__getitem__)
                verified.action = action
        kept.append(verified)
    return kept, notes


def action_json(action: CheckedAction | None) -> dict[str, Any] | None:
    if action is None:
        return None
    return {
        "kind": action.kind,
        "statement": action.statement,
        "table": action.table,
        "reason": action.reason,
        "risk": action.risk,
    }
