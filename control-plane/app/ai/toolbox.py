"""The graph's toolbox for real runs: statistics and table search for ONE datasource.

The datasource is fixed when the toolbox is made; the graph and the model cannot reach any
other. Fresh statistics are asked from the connector when the stored ones are older than
FRESH; when the connector is offline the last stored ones are used and the answer says how
old they are.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.ai import facts
from app.ai.graph import Snapshots
from app.core.db import SessionFactory
from app.gateway.hub import ConnectorHub
from app.models import Connector, Datasource
from app.models.enums import Collector
from app.schemas.snapshots import DATA_MODELS
from app.services import collect as collect_svc
from app.services import snapshots as snapshots_svc
from app.services import table_search
from app.services.table_search import Match, SearchResult

logger = logging.getLogger(__name__)

FRESH = timedelta(minutes=5)

LABELS = {
    Collector.HEALTH: "Health",
    Collector.LOCKS: "Locks",
    Collector.TABLE_STATS: "Table statistics",
    Collector.INDEXES: "Index statistics",
    Collector.SLOW_QUERIES: "Slow statements",
    Collector.TABLE_INDEX: "Table list",
}
_FIELDS = {
    Collector.HEALTH: "health",
    Collector.LOCKS: "locks",
    Collector.TABLE_STATS: "tables",
    Collector.INDEXES: "indexes",
    Collector.SLOW_QUERIES: "queries",
}


class LiveToolbox:
    def __init__(
        self,
        sessions: SessionFactory,
        hub: ConnectorHub,
        datasource_id: uuid.UUID,
    ) -> None:
        self._sessions = sessions
        self._hub = hub
        self._datasource_id = datasource_id

    async def _refresh(self, collectors: set[Collector], max_age: timedelta | None) -> list[str]:
        """Ask the connector for collectors older than max_age; notes on what failed."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Datasource, Connector)
                    .join(Connector, Connector.id == Datasource.connector_id)
                    .where(Datasource.id == self._datasource_id)
                )
            ).one()
            ds, connector = row.Datasource, row.Connector
            if ds.engine not in collect_svc.SUPPORTED_ENGINES:
                return [f"Statistics are not available for {ds.engine} yet."]
            if not self._hub.is_online(connector.id):
                return [f"The connector {connector.name} is offline; the last statistics are used."]
            errors = await collect_svc.collect(
                session, self._hub, ds, connector, collectors, max_age=max_age
            )
        return [f"{LABELS[Collector(e.collector)]}: {e.message}" for e in errors]

    async def gather(self, collectors: set[Collector]) -> Snapshots:
        wanted = {c for c in collectors if c in _FIELDS}
        snaps = Snapshots(notes=await self._refresh(wanted, FRESH))
        async with self._sessions() as session:
            latest = await snapshots_svc.latest(session, self._datasource_id, wanted)
        now = datetime.now(UTC)
        for collector in sorted(wanted):
            snapshot = latest.get(collector)
            if snapshot is None:
                snaps.notes.append(f"{LABELS[collector]}: not collected yet.")
                continue
            data = DATA_MODELS[collector].model_validate(snapshot.data)
            setattr(snaps, _FIELDS[collector], data)
            note = facts.age_note(LABELS[collector], snapshot.collected_at, now)
            if note:
                snaps.notes.append(note)
        return snaps

    async def _index_ready(self) -> list[str]:
        # The table list is refreshed at most every 10 minutes (its own minimum interval).
        return await self._refresh({Collector.TABLE_INDEX}, None)

    async def find_tables(self, words: str, period: str | None) -> SearchResult | None:
        notes = await self._index_ready()
        async with self._sessions() as session:
            try:
                result = await table_search.find_tables(
                    session, self._datasource_id, words, period=period
                )
            except table_search.NoTableIndexError:
                logger.info("no table index", extra={"datasource_id": str(self._datasource_id)})
                return None
        result.notes = notes + result.notes
        return result

    async def table_named(self, name: str, period: str | None) -> Match | None:
        await self._index_ready()
        async with self._sessions() as session:
            try:
                return await table_search.find_named(
                    session, self._datasource_id, name, period=period
                )
            except table_search.NoTableIndexError:
                return None
