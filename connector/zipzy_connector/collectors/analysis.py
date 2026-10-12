"""Findings worked out from index and table metadata. Engine-independent, pure functions.

Index:        {schema, table, name, columns, unique, primary, size_bytes, scans, valid, partial,
               expression}
Foreign key:  {schema, table, name, columns, references}
"""

from typing import Any

MAX_FINDINGS = 100  # per kind; the biggest problems first

# A table this small is fast to scan; full scans on it are not worth reporting.
FULL_SCAN_MIN_ROWS = 10_000


def _key(ix: dict[str, Any]) -> tuple[str, str]:
    return (str(ix["schema"]), str(ix["table"]))


def _plain(ix: dict[str, Any]) -> bool:
    """Ordinary column index: comparable by its column list."""
    return bool(ix.get("valid", True)) and not ix.get("partial") and not ix.get("expression")


def unused_indexes(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never used since the statistics started. Primary and unique indexes enforce rules: kept."""
    found = [
        {
            "schema": ix["schema"],
            "table": ix["table"],
            "index": ix["name"],
            "columns": ix["columns"],
            "size_bytes": ix.get("size_bytes"),
        }
        for ix in indexes
        if ix.get("scans") == 0 and not ix["primary"] and not ix["unique"]
    ]
    found.sort(key=lambda f: -(f["size_bytes"] or 0))
    return found[:MAX_FINDINGS]


def duplicate_indexes(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An index whose columns are the leading columns of another index on the same table.

    The longer index can serve every query the shorter one serves, so the shorter one only costs
    disk and slows writes. Not reported: primary keys, and unique indexes on fewer columns (they
    enforce a rule the longer index does not).
    """
    by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ix in indexes:
        if _plain(ix):
            by_table.setdefault(_key(ix), []).append(ix)

    found: list[dict[str, Any]] = []
    for group in by_table.values():
        reported: set[str] = set()
        for a in group:
            if a["primary"]:
                continue
            for b in group:
                if a is b or b["name"] in reported:
                    continue
                n = len(a["columns"])
                if n == 0 or b["columns"][:n] != a["columns"]:
                    continue
                same = len(b["columns"]) == n
                if a["unique"] and not (same and b["unique"]):
                    continue  # a unique rule on fewer columns is not redundant
                if same and not b["primary"] and a["name"] < b["name"]:
                    continue  # identical twins: report only one of the two
                found.append(
                    {
                        "schema": a["schema"],
                        "table": a["table"],
                        "index": a["name"],
                        "columns": a["columns"],
                        "covered_by": b["name"],
                        "size_bytes": a.get("size_bytes"),
                    }
                )
                reported.add(a["name"])
                break
    found.sort(key=lambda f: (-(f["size_bytes"] or 0), f["schema"], f["table"], f["index"]))
    return found[:MAX_FINDINGS]


def unindexed_foreign_keys(
    foreign_keys: list[dict[str, Any]], indexes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Foreign keys whose columns do not lead any index: joins and deletes on the parent scan."""
    leading: dict[tuple[str, str], list[list[str]]] = {}
    for ix in indexes:
        if _plain(ix):
            leading.setdefault(_key(ix), []).append(list(ix["columns"]))

    found: list[dict[str, Any]] = []
    for fk in foreign_keys:
        cols = list(fk["columns"])
        if not cols:
            continue
        covered = any(set(c[: len(cols)]) == set(cols) for c in leading.get(_key(fk), []))
        if not covered:
            found.append(
                {
                    "schema": fk["schema"],
                    "table": fk["table"],
                    "constraint": fk["name"],
                    "columns": cols,
                    "references": fk["references"],
                }
            )
    found.sort(key=lambda f: (f["schema"], f["table"], f["constraint"]))
    return found[:MAX_FINDINGS]


def invalid_indexes(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Postgres: an index left broken by a failed CREATE INDEX CONCURRENTLY. Costs, never used."""
    return [
        {"schema": ix["schema"], "table": ix["table"], "index": ix["name"]}
        for ix in indexes
        if ix.get("valid") is False
    ][:MAX_FINDINGS]
