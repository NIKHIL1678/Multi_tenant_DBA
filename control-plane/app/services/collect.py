"""Ask a datasource's connector to run collectors, validate the answers and store them.

Used by the server page ("Collect now") and by the AI agents, so both see the same numbers.
Collectors run in parallel; one failing does not stop the others. A collector that ran within
`max_age` is not asked again (its stored answer is reused).
"""

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.hub import (
    ConnectorHub,
    ConnectorOfflineError,
    RequestTimeoutError,
    ToolFailedError,
)
from app.models import Connector, Datasource
from app.models.enums import Collector, DbEngine
from app.schemas.snapshots import DATA_MODELS, CollectError
from app.services import snapshots as svc

COLLECT_TIMEOUT_SECONDS = 45  # the connector gives each collector 30 s
SUPPORTED_ENGINES = frozenset({DbEngine.POSTGRES, DbEngine.MYSQL, DbEngine.MARIADB})
# Connector version that first offered each collector (an older one answers "unknown_tool").
FIRST_VERSION = {
    Collector.HEALTH: "0.4.0",
    Collector.TABLE_STATS: "0.4.0",
    Collector.INDEXES: "0.4.0",
    Collector.SLOW_QUERIES: "0.6.0",
    Collector.LOCKS: "0.6.0",
    Collector.TABLE_INDEX: "0.6.0",
}


def outdated(collector: Collector) -> str:
    return f"Update the connector to version {FIRST_VERSION[collector]} or newer to collect this."


def unsupported(ds: Datasource, collectors: Iterable[Collector]) -> list[CollectError]:
    return [
        CollectError(collector=c, code="unsupported", message=f"Not available for {ds.engine} yet.")
        for c in collectors
    ]


async def collect(
    session: AsyncSession,
    hub: ConnectorHub,
    ds: Datasource,
    connector: Connector,
    collectors: Iterable[Collector],
    *,
    max_age: timedelta | None = None,
) -> list[CollectError]:
    """Run the collectors that are older than `max_age` (default: each one's minimum interval),
    store what they return and commit. Returns the collectors that failed, with why.

    The caller checks that the connector is online and the engine is supported.
    """
    wanted = list(dict.fromkeys(collectors))
    ran_at = await svc.last_collected(session, ds.id, wanted)
    now = datetime.now(UTC)
    if max_age is None:
        todo = [c for c in wanted if not svc.is_fresh(c, ran_at.get(c), now)]
    else:
        todo = [c for c in wanted if c not in ran_at or now - ran_at[c] >= max_age]

    async def run(collector: Collector) -> tuple[Collector, dict[str, Any] | CollectError]:
        def failed(code: str, message: str) -> tuple[Collector, CollectError]:
            return collector, CollectError(collector=collector, code=code, message=message)

        try:
            result = await hub.request(
                connector.id,
                collector,
                {"datasource": ds.local_name},
                wait_seconds=COLLECT_TIMEOUT_SECONDS,
            )
            data = DATA_MODELS[collector].model_validate(result)
        except ToolFailedError as exc:
            if exc.code == "unknown_tool":
                return failed("outdated_connector", outdated(collector))
            return failed(exc.code, exc.message)
        except RequestTimeoutError:
            return failed("timeout", "The connector did not answer in time.")
        except ConnectorOfflineError:
            return failed("offline", f"Connector {connector.name} went offline.")
        except ValidationError:
            return failed("bad_answer", "The connector sent an unexpected answer.")
        return collector, data.model_dump(mode="json")

    errors: list[CollectError] = []
    for collector, outcome in await asyncio.gather(*(run(c) for c in todo)):
        if isinstance(outcome, CollectError):
            errors.append(outcome)
        else:
            await svc.store(session, ds, collector, outcome)
    await session.commit()
    return errors
