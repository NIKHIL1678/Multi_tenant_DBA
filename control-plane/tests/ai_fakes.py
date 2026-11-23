"""Fakes for agent tests: a scripted model and a toolbox with fixed statistics."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.ai.graph import Snapshots
from app.ai.llm import AIUnavailableError, Usage
from app.models.enums import Collector
from app.schemas.snapshots import (
    HealthData,
    IndexesData,
    LocksData,
    SlowQueriesData,
    TableIndexData,
    TableStatsData,
)
from app.services import table_search
from app.services.table_search import Match, SearchResult

T = TypeVar("T", bound=BaseModel)
Script = BaseModel | Exception | Callable[[str, str], BaseModel]


@dataclass
class Call:
    name: str
    system: str
    user: str


class FakeLLM:
    """Answers each call by its name ("plan", "specialist_query", "answer"…) from a script."""

    def __init__(self, **script: Script | list[Script]) -> None:
        self.script = {k: v if isinstance(v, list) else [v] for k, v in script.items()}
        self.calls: list[Call] = []

    async def structured(
        self, *, system: str, user: str, output: type[T], name: str
    ) -> tuple[T, Usage]:
        self.calls.append(Call(name, system, user))
        if name not in self.script:
            raise AssertionError(f"unexpected model call: {name}")
        queue = self.script[name]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        value = item(system, user) if callable(item) and not isinstance(item, BaseModel) else item
        assert isinstance(value, output), f"{name} scripted {type(value)} not {output}"
        return value, Usage(100, 20, ["fake-model"])

    def names(self) -> list[str]:
        return [c.name for c in self.calls]


HEALTH = HealthData.model_validate(
    {
        "uptime_seconds": 90_000,
        "connections": {"current": 140, "active": 12, "max": 151},
        "cache_hit_ratio": 0.97,
        "throughput_per_second": 35.0,
        "settings": {"max_connections": "151"},
    }
)
LOCKS = LocksData.model_validate(
    {
        "available": True,
        "waits": [
            {
                "waiting_session": 31,
                "wait_seconds": 12,
                "blocking_session": 27,
                "blocker_transaction_seconds": 340,
                "schema": "hrm",
                "table": "attendance",
            }
        ],
        "long_transactions": [{"session": 27, "seconds": 340, "state": "RUNNING"}],
    }
)
TABLES = TableStatsData.model_validate(
    {
        "total_tables": 3,
        "tables": [
            {
                "schema": "hrm",
                "name": "attendance",
                "rows": 200_000,
                "data_bytes": 7_000_000,
                "index_bytes": 100_000,
                "has_primary_key": True,
            },
            {"schema": "hrm", "name": "employees", "rows": 500, "has_primary_key": True},
            {"schema": "payroll", "name": "attendance", "rows": 50, "has_primary_key": False},
        ],
    }
)
INDEXES = IndexesData.model_validate(
    {
        "total_indexes": 3,
        "indexes": [
            {
                "schema": "hrm",
                "table": "attendance",
                "name": "PRIMARY",
                "columns": ["id"],
                "unique": True,
                "primary": True,
            },
            {
                "schema": "hrm",
                "table": "attendance",
                "name": "idx_status",
                "columns": ["status"],
                "unique": False,
                "primary": False,
                "scans": 0,
            },
            {
                "schema": "hrm",
                "table": "employees",
                "name": "PRIMARY",
                "columns": ["id"],
                "unique": True,
                "primary": True,
            },
        ],
        "unused": [
            {
                "schema": "hrm",
                "table": "attendance",
                "index": "idx_status",
                "columns": ["status"],
                "size_bytes": 4096,
            }
        ],
        "missing_primary_keys": [{"schema": "payroll", "table": "attendance", "rows": 50}],
        "full_scans": [
            {
                "schema": "hrm",
                "table": "attendance",
                "rows": 200_000,
                "rows_read_without_index": 82_400_000,
            }
        ],
    }
)
QUERIES = SlowQueriesData.model_validate(
    {
        "available": True,
        "total_statements": 2,
        "queries": [
            {
                "id": "d1",
                "database": "hrm",
                "text": "SELECT `status` FROM `hrm` . `attendance` "
                "WHERE `emp_id` = ? AND SQL_TSI_DAY = ?",
                "calls": 412,
                "total_ms": 98_000.0,
                "mean_ms": 237.9,
                "rows_examined": 82_400_000,
                "rows_returned": 412,
                "no_index_used": 412,
            },
            {
                "id": "d2",
                "database": "hrm",
                "text": "SELECT * FROM `hrm` . `employees` WHERE `id` = ?",
                "calls": 9000,
                "total_ms": 900.0,
                "mean_ms": 0.1,
            },
        ],
    }
)
INDEX = TableIndexData.model_validate(
    {
        "total_tables": 3,
        "listed_tables": 3,
        "schemas": [
            {
                "name": "hrm",
                "tables": [["attendance", 200_000, 7_100_000], ["employees", 500, 65536]],
            },
            {"name": "payroll", "tables": [["attendance", 50, 16384]]},
        ],
    }
)


@dataclass
class FakeTools:
    index: TableIndexData | None = field(default_factory=lambda: INDEX)
    notes: list[str] = field(default_factory=list)
    gathered: list[set[Collector]] = field(default_factory=list)

    async def gather(self, collectors: set[Collector]) -> Snapshots:
        self.gathered.append(set(collectors))
        return Snapshots(
            health=HEALTH if Collector.HEALTH in collectors else None,
            locks=LOCKS if Collector.LOCKS in collectors else None,
            tables=TABLES if Collector.TABLE_STATS in collectors else None,
            indexes=INDEXES if Collector.INDEXES in collectors else None,
            queries=QUERIES if Collector.SLOW_QUERIES in collectors else None,
            notes=list(self.notes),
        )

    async def find_tables(self, words: str, period: str | None) -> SearchResult | None:
        if self.index is None:
            return None
        return table_search.search(self.index, words, period=period)

    async def table_named(self, name: str, period: str | None) -> Match | None:
        if self.index is None:
            return None
        return table_search.match_named(self.index, name, period=period)


def unavailable(message: str = "The AI service is busy; try again in a minute.") -> Exception:
    return AIUnavailableError(message)


def any_of(*items: Any) -> Any:
    return items
