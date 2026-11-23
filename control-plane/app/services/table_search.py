"""Find tables by name among thousands — the first step before an agent looks at a table.

Works on the latest `table_index` snapshot (every table's name, rows and size), never on the
customer's database directly, so a search is instant and puts no load on their server.

- **Families.** Tables that differ only by a date or number at the end (attendance_2024_01,
  attendance_2024_02 …, orders_p1, orders_p2 …) are one family, so 1,200 monthly tables are one
  result, not 1,200. A member whose suffix is a date carries its period ("2024-01").
- **Matching.** Words of the question are matched to words of schema and table names: exact,
  prefix ("attend" → attendance) or a small typo ("attendence"). Words that match no name at
  all ("lowest", "employee who …") are ignored, as are time words: the period is passed apart.
- **Ranking.** Better name match first; between equal matches, the bigger table.
- **Periods.** Given a period ("2026-11"), results that have a table for it rank above equal
  matches that do not, and a family lists that period's tables.
- **Ambiguity.** When the top two results match about equally well, `ambiguous` is set so the
  caller asks the person which one they mean instead of guessing.

Names come from the customer's database: they are data, never instructions.
"""

import math
import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Snapshot
from app.models.enums import Collector
from app.schemas.snapshots import TableIndexData

MAX_RESULTS = 25
FAMILY_SAMPLE = 5  # members listed per family
MIN_SCORE = 0.5  # weaker matches are not results
AMBIGUOUS_GAP = 0.05  # top two closer than this -> ask which one instead of guessing
PERIOD_BONUS = 0.06  # has a table for the asked period: beats an equal match without one
TYPO_RATIO = 0.8  # "attendence" ~ "attendance"
SCHEMA_WEIGHT = 0.6  # a word matching the schema counts less than one matching the table

# Words that say nothing about which table is meant.
# Months and other time words are not table names: the caller passes the period separately.
_STOPWORD_TEXT = (
    "a an the of for in on to from by with and or is are was were has have had my our me us i "
    "show list find get give tell all any each which what where who whom whose how many much "
    "table tables data database db rows row record records details info information about "
    "please lowest highest least most top bottom best worst last first this current previous "
    "today yesterday week month year day date january february march april may june july "
    "august september october november december jan feb mar apr jun jul aug sep sept oct nov "
    "dec"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

# A trailing date (YYYY, YYYYMM, YYYY_MM, YYYY_MM_DD …) or number (12, p3) after a name.
_SUFFIX = re.compile(
    r"^(?P<base>.*?[A-Za-z])(?P<sep>[_\-]?)"
    r"(?P<suffix>(?:19|20)\d{2}(?:[_\-]?(?:0[1-9]|1[0-2])(?:[_\-]?(?:0[1-9]|[12]\d|3[01]))?)?"
    r"|[pP]?\d{1,6})$"
)
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def words(text: str) -> list[str]:
    """'empAttendance_2024' -> ['emp', 'attendance', '2024']."""
    return [w.lower() for w in _WORDS.findall(text)]


def period_of(suffix: str) -> str | None:
    """'2024_01' -> '2024-01', '20240115' -> '2024-01-15', '2024' -> '2024', '12' -> None."""
    digits = re.sub(r"\D", "", suffix)
    if not re.fullmatch(r"(19|20)\d{2}(\d{2}(\d{2})?)?", digits):
        return None
    return "-".join(p for p in (digits[:4], digits[4:6], digits[6:8]) if p)


@dataclass(frozen=True, slots=True)
class Table:
    schema: str
    name: str
    rows: int | None
    bytes: int | None
    period: str | None = None


@dataclass(slots=True)
class Candidate:
    """One table, or one family of tables, that a search can return."""

    kind: Literal["table", "family"]
    schema: str
    name: str  # table name, or the family pattern such as "attendance_*"
    tables: list[Table]
    name_words: frozenset[str]
    schema_words: frozenset[str]

    @property
    def bytes(self) -> int:
        return sum(t.bytes or 0 for t in self.tables)

    @property
    def rows(self) -> int | None:
        known = [t.rows for t in self.tables if t.rows is not None]
        return sum(known) if known else None


@dataclass(frozen=True, slots=True)
class Match:
    kind: Literal["table", "family"]
    schema: str
    name: str
    score: float
    rows: int | None
    bytes: int
    table_count: int
    periods: tuple[str, str] | None  # first and last period of a dated family
    tables: list[Table]  # the table, or up to FAMILY_SAMPLE members (those of `period` first)


@dataclass(slots=True)
class SearchResult:
    query: str
    matches: list[Match]
    ambiguous: bool  # ask the person which match they mean
    index_truncated: bool  # the index lists only the biggest tables
    notes: list[str] = field(default_factory=list)


def build_candidates(index: TableIndexData) -> list[Candidate]:
    """Group the index into single tables and families (2+ tables sharing a name and suffix)."""
    groups: dict[tuple[str, str, str], list[Table]] = {}
    singles: list[Table] = []
    for listed in index.schemas:
        for name, rows, size in listed.tables:
            m = _SUFFIX.match(name)
            table = Table(listed.name, name, rows, size, period_of(m["suffix"]) if m else None)
            if m:
                groups.setdefault((listed.name, m["base"], m["sep"]), []).append(table)
            else:
                singles.append(table)

    candidates: list[Candidate] = []
    for (schema, base, sep), members in groups.items():
        if len(members) == 1:
            singles.append(members[0])
            continue
        members.sort(key=lambda t: (t.period or "", t.name))
        candidates.append(
            Candidate(
                "family",
                schema,
                f"{base}{sep}*",
                members,
                frozenset(words(base)),
                frozenset(words(schema)),
            )
        )
    candidates.extend(
        Candidate(
            "table",
            t.schema,
            t.name,
            [t],
            frozenset(w for w in words(t.name) if not w.isdigit()),
            frozenset(words(t.schema)),
        )
        for t in singles
    )
    return candidates


def _similarity(q: str, w: str) -> float:
    if q == w:
        return 1.0
    if min(len(q), len(w)) >= 3 and (w.startswith(q) or q.startswith(w)):
        return 0.9
    if min(len(q), len(w)) >= 4:
        ratio = SequenceMatcher(None, q, w).ratio()
        if ratio >= TYPO_RATIO:
            return 0.9 * ratio
    return 0.0


def query_words(query: str) -> list[str]:
    return [w for w in dict.fromkeys(words(query)) if w not in STOPWORDS and not w.isdigit()]


def _score(c: Candidate, wanted: list[str], sim: dict[tuple[str, str], float]) -> float:
    total = 0.0
    hit_name = False
    for q in wanted:
        in_name = max((sim[(q, w)] for w in c.name_words), default=0.0)
        in_schema = SCHEMA_WEIGHT * max((sim[(q, w)] for w in c.schema_words), default=0.0)
        hit_name = hit_name or in_name > 0
        total += max(in_name, in_schema)
    if not hit_name:
        return 0.0  # a schema match alone would return every table of that schema
    score = total / len(wanted)
    if score >= MIN_SCORE:
        # Bigger tables first among equal matches; never enough to beat a better name match.
        score += 0.01 * min(math.log10(1 + c.bytes) / 12, 1.0)
    return round(score, 4)


def _members(c: Candidate, period: str | None) -> tuple[list[Table], list[str]]:
    if c.kind == "table":
        return c.tables, []
    if period:
        inside = [t for t in c.tables if t.period and t.period.startswith(period)]
        if inside:
            return inside[:FAMILY_SAMPLE], []
        dated = [t for t in c.tables if t.period]
        if dated:
            before = [t for t in dated if t.period and t.period < period]
            nearest = before[-1] if before else dated[0]
            return [nearest], [
                f"{c.schema}.{c.name} has no table for {period}; the nearest is {nearest.name}."
            ]
    biggest = sorted(c.tables, key=lambda t: -(t.bytes or 0))[:FAMILY_SAMPLE]
    return biggest, []


def search(
    index: TableIndexData,
    query: str,
    *,
    schema: str | None = None,
    period: str | None = None,
    limit: int = 10,
    candidates: list[Candidate] | None = None,
) -> SearchResult:
    """Best tables or families for `query`, optionally within one schema (database)."""
    limit = max(1, min(limit, MAX_RESULTS))
    wanted = query_words(query)
    result = SearchResult(query=query, matches=[], ambiguous=False, index_truncated=index.truncated)
    if index.truncated:
        result.notes.append(
            f"Only the {index.listed_tables:,} biggest of {index.total_tables:,} tables are "
            "searched."
        )
    if not wanted:
        result.notes.append("The question names no table.")
        return result

    pool = candidates if candidates is not None else build_candidates(index)
    if schema is not None:
        pool = [c for c in pool if c.schema == schema]
    vocabulary = {w for c in pool for w in c.name_words | c.schema_words}
    sim = {(q, w): _similarity(q, w) for q in wanted for w in vocabulary}
    # Words that match no schema or table at all ("employee who has the lowest …") are about
    # something else; they must not lower every score.
    wanted = [q for q in wanted if any(sim[(q, w)] for w in vocabulary)]
    if not wanted:
        result.notes.append("No schema or table name matches the question.")
        return result

    scored = [(s, c) for c in pool if (s := _score(c, wanted, sim)) >= MIN_SCORE]
    if period:
        scored = [
            (round(s + PERIOD_BONUS, 4) if _has_period(c, period) else s, c) for s, c in scored
        ]
    scored.sort(key=lambda sc: (-sc[0], sc[1].schema, sc[1].name))
    for score, c in scored[:limit]:
        tables, notes = _members(c, period)
        dated = [t.period for t in c.tables if t.period]
        result.matches.append(
            Match(
                kind=c.kind,
                schema=c.schema,
                name=c.name,
                score=score,
                rows=c.rows,
                bytes=c.bytes,
                table_count=len(c.tables),
                periods=(dated[0], dated[-1]) if c.kind == "family" and dated else None,
                tables=tables,
            )
        )
        result.notes.extend(notes)

    top = result.matches
    result.ambiguous = len(top) >= 2 and top[0].score - top[1].score < AMBIGUOUS_GAP
    return result


def _has_period(c: Candidate, period: str) -> bool:
    return any(t.period and t.period.startswith(period) for t in c.tables)


# ---- loading the index -----------------------------------------------------------------------


class NoTableIndexError(Exception):
    """table_index was never collected for this datasource."""


_CACHE: OrderedDict[uuid.UUID, tuple[TableIndexData, list[Candidate]]] = OrderedDict()
_CACHE_SIZE = 8


async def load_index(
    session: AsyncSession, datasource_id: uuid.UUID
) -> tuple[TableIndexData, list[Candidate]]:
    """The latest table index of a datasource, parsed once per snapshot and kept in memory."""
    snapshot_id = await session.scalar(
        select(Snapshot.id)
        .where(
            Snapshot.datasource_id == datasource_id,
            Snapshot.collector == Collector.TABLE_INDEX,
        )
        .order_by(Snapshot.collected_at.desc())
        .limit(1)
    )
    if snapshot_id is None:
        raise NoTableIndexError
    cached = _CACHE.get(snapshot_id)
    if cached is None:
        data = await session.scalar(select(Snapshot.data).where(Snapshot.id == snapshot_id))
        index = TableIndexData.model_validate(data)
        cached = (index, build_candidates(index))
        _CACHE[snapshot_id] = cached
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    _CACHE.move_to_end(snapshot_id)
    return cached


async def find_tables(
    session: AsyncSession,
    datasource_id: uuid.UUID,
    query: str,
    *,
    schema: str | None = None,
    period: str | None = None,
    limit: int = 10,
) -> SearchResult:
    """Search the datasource's latest table index (raises NoTableIndexError if there is none).

    The caller must already have checked that the user may see this datasource.
    """
    index, candidates = await load_index(session, datasource_id)
    return search(index, query, schema=schema, period=period, limit=limit, candidates=candidates)
