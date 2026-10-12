"""Snapshots: what collectors found on a datasource, one row per run.

- The latest row per collector is what pages show; older rows are kept for trends.
- Rows older than RETENTION_DAYS are removed whenever a new one is stored.
- A collector that ran less than MIN_INTERVAL_SECONDS ago is not asked again: its last answer
  is reused, so repeated clicks cannot put load on the customer's database.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Datasource, Snapshot
from app.models.enums import Collector

MIN_INTERVAL_SECONDS = 30
RETENTION_DAYS = 30


async def latest(session: AsyncSession, datasource_id: uuid.UUID) -> dict[Collector, Snapshot]:
    rows = await session.scalars(
        select(Snapshot)
        .where(Snapshot.datasource_id == datasource_id)
        .ext(distinct_on(Snapshot.collector))
        .order_by(Snapshot.collector, Snapshot.collected_at.desc())
    )
    return {Collector(s.collector): s for s in rows}


def is_fresh(snapshot: Snapshot | None, now: datetime) -> bool:
    return snapshot is not None and now - snapshot.collected_at < timedelta(
        seconds=MIN_INTERVAL_SECONDS
    )


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
    session.add(snapshot)
    await session.execute(
        delete(Snapshot).where(
            Snapshot.datasource_id == datasource.id,
            Snapshot.collector == collector,
            Snapshot.collected_at < now - timedelta(days=RETENTION_DAYS),
        )
    )
    await session.flush()
    return snapshot
