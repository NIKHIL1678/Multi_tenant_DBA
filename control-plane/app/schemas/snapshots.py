"""What collectors return (connector 0.4.0+), validated before it is stored or shown.

The connector is authenticated but its answers are still checked: known shape, bounded lists,
sensible numbers. Unknown extra fields are ignored so a newer connector keeps working.
Names of schemas, tables, columns and indexes are metadata; no table rows are ever included.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Collector

Count = Annotated[int, Field(ge=0)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
Columns = Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=64)]


class _In(BaseModel):
    # The wire name "schema" would shadow BaseModel.schema(), so the attribute is `schema_name`
    # and "schema" is its alias in both directions.
    model_config = ConfigDict(
        extra="ignore",
        validate_by_name=True,
        serialize_by_alias=True,
        # Every field is always sent, so the generated dashboard types mark none as optional.
        json_schema_serialization_defaults_required=True,
    )


SchemaName = Annotated[str, Field(min_length=1, max_length=200, alias="schema")]


# ---- health ----------------------------------------------------------------------------------


class Connections(_In):
    current: Count | None = None
    active: Count | None = None
    max: Count | None = None
    peak: Count | None = None  # most at once since start (MySQL only)


class Replication(_In):
    is_replica: bool | None = None  # None: the monitoring user may not look
    lag_seconds: float | None = None


class HealthData(_In):
    uptime_seconds: Count | None = None
    connections: Connections = Connections()
    cache_hit_ratio: Annotated[float, Field(ge=0, le=1)] | None = None
    throughput_per_second: Annotated[float, Field(ge=0)] | None = None
    throughput_unit: str = "queries"  # queries (MySQL) or transactions (Postgres)
    deadlocks: Count | None = None
    slow_queries: Count | None = None
    temp_tables_on_disk_ratio: Annotated[float, Field(ge=0, le=1)] | None = None
    replication: Replication = Replication()
    settings: Annotated[dict[str, Annotated[str, Field(max_length=200)]], Field(max_length=50)] = {}


# ---- table_stats -----------------------------------------------------------------------------


class TableRow(_In):
    schema_name: SchemaName
    name: Name
    engine: str | None = None
    rows: Count | None = None  # the server's estimate
    data_bytes: Count | None = None
    index_bytes: Count | None = None
    free_bytes: Count | None = None  # MySQL: space to reclaim
    dead_rows: Count | None = None  # Postgres: rows waiting for VACUUM
    has_primary_key: bool
    seq_scans: Count | None = None  # Postgres: full scans since stats reset
    index_scans: Count | None = None


class TableStatsData(_In):
    total_tables: Count
    truncated: bool = False  # only the biggest are listed
    tables: Annotated[list[TableRow], Field(max_length=1000)]


# ---- indexes ---------------------------------------------------------------------------------


class IndexRow(_In):
    schema_name: SchemaName
    table: Name
    name: Name
    columns: Columns
    unique: bool
    primary: bool
    size_bytes: Count | None = None
    scans: Count | None = None  # None: usage not known
    valid: bool = True
    partial: bool = False
    expression: bool = False


class UnusedIndex(_In):
    schema_name: SchemaName
    table: Name
    index: Name
    columns: Columns
    size_bytes: Count | None = None


class DuplicateIndex(_In):
    schema_name: SchemaName
    table: Name
    index: Name
    columns: Columns
    covered_by: Name
    size_bytes: Count | None = None


class UnindexedForeignKey(_In):
    schema_name: SchemaName
    table: Name
    constraint: Name
    columns: Columns
    references: Name


class MissingPrimaryKey(_In):
    schema_name: SchemaName
    table: Name
    rows: Count | None = None


class FullScan(_In):
    schema_name: SchemaName
    table: Name
    rows: Count | None = None
    full_scans: Count | None = None  # Postgres
    rows_read_without_index: Count | None = None  # MySQL


class InvalidIndex(_In):
    schema_name: SchemaName
    table: Name
    index: Name


def _findings() -> Any:
    return Field(default_factory=list, max_length=200)


class IndexesData(_In):
    usage_since: datetime | None = None  # usage counters restart with the server
    total_indexes: Count
    truncated: bool = False
    indexes: Annotated[list[IndexRow], Field(max_length=1000)]
    unused: list[UnusedIndex] = _findings()
    duplicates: list[DuplicateIndex] = _findings()
    unindexed_foreign_keys: list[UnindexedForeignKey] = _findings()
    missing_primary_keys: list[MissingPrimaryKey] = _findings()
    full_scans: list[FullScan] = _findings()
    invalid: list[InvalidIndex] = _findings()


DATA_MODELS: dict[Collector, type[_In]] = {
    Collector.HEALTH: HealthData,
    Collector.TABLE_STATS: TableStatsData,
    Collector.INDEXES: IndexesData,
}


# ---- API -------------------------------------------------------------------------------------


class HealthSnapshot(BaseModel):
    collected_at: datetime
    data: HealthData


class TableStatsSnapshot(BaseModel):
    collected_at: datetime
    data: TableStatsData


class IndexesSnapshot(BaseModel):
    collected_at: datetime
    data: IndexesData


class CollectError(BaseModel):
    collector: Collector
    code: str  # offline | timeout | unsupported | outdated_connector | collector_failed | ...
    message: str


class ServerSnapshotsOut(BaseModel):
    """The latest answer of each collector for one datasource (None: never collected)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    datasource_id: uuid.UUID
    health: HealthSnapshot | None
    table_stats: TableStatsSnapshot | None
    indexes: IndexesSnapshot | None
    errors: list[CollectError] = []  # filled by POST .../collect for collectors that failed


class CollectIn(BaseModel):
    collectors: Annotated[list[Collector], Field(min_length=1, max_length=len(Collector))] = list(
        Collector
    )
