"""Snapshots: what collectors found on a datasource, one row per run.

- The latest row per collector is what pages show; older rows are kept for trends.
- Rows older than RETENTION_DAYS are removed whenever a new one is stored. table_index keeps
  only its latest row: it can be megabytes and only the current list of tables matters.
- A collector that ran recently is not asked again: its last answer is reused, so repeated
  clicks cannot put load on the customer's database (MIN_INTERVAL_SECONDS, longer for
  table_index, which reads the whole catalog).
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Datasource, Snapshot
from app.models.enums import Collector

MIN_INTERVAL_SECONDS = 30
TABLE_INDEX_MIN_INTERVAL_SECONDS = 600
RETENTION_DAYS = 30
KEEP_LATEST_ONLY = frozenset({Collector.TABLE_INDEX})


def min_interval(collector: Collector) -> timedelta:
    if collector is Collector.TABLE_INDEX:
        return timedelta(seconds=TABLE_INDEX_MIN_INTERVAL_SECONDS)
    return timedelta(seconds=MIN_INTERVAL_SECONDS)


async def latest(
    session: AsyncSession, datasource_id: uuid.UUID, collectors: Iterable[Collector]
) -> dict[Collector, Snapshot]:
    """The newest snapshot of each of `collectors` (missing: never collected)."""
    wanted = [c.value for c in collectors]
    rows = await session.scalars(
        select(Snapshot)
        .where(Snapshot.datasource_id == datasource_id, Snapshot.collector.in_(wanted))
        .ext(distinct_on(Snapshot.collector))
        .order_by(Snapshot.collector, Snapshot.collected_at.desc())
    )
    return {Collector(s.collector): s for s in rows}


async def last_collected(
    session: AsyncSession, datasource_id: uuid.UUID, collectors: Iterable[Collector]
) -> dict[Collector, datetime]:
    """When each of `collectors` last ran (times only: table_index rows can be megabytes)."""
    rows = await session.execute(
        select(Snapshot.collector, func.max(Snapshot.collected_at))
        .where(
            Snapshot.datasource_id == datasource_id,
            Snapshot.collector.in_([c.value for c in collectors]),
        )
        .group_by(Snapshot.collector)
    )
    return {Collector(c): at for c, at in rows}


def is_fresh(collector: Collector, collected_at: datetime | None, now: datetime) -> bool:
    """Ran so recently that its last answer is reused instead of asking the database again."""
    return collected_at is not None and now - collected_at < min_interval(collector)


async def store(
    session: AsyncSession, datasource: Datasource, collector: Collector, data: dict[str, Any]
) -> Snapshot:
    now = datetime.now(UTC)
    snapshot = Snapshot(
        tenant_id=datasource.tenant_id,
        datasource_id=datasource.id,
        collector=collector,
        data=data,
        collected_at=now,
    )
    cutoff = now if collector in KEEP_LATEST_ONLY else now - timedelta(days=RETENTION_DAYS)
    await session.execute(
        delete(Snapshot).where(
            Snapshot.datasource_id == datasource.id,
            Snapshot.collector == collector,
            Snapshot.collected_at < cutoff,
        )
    )
    session.add(snapshot)
    await session.flush()
    return snapshot
