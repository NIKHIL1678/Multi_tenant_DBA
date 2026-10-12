"""Collectors: read-only statistics about one datasource, gathered by its connector.

GET  /v1/tenants/{tenant_id}/datasources/{datasource_id}/snapshots   latest answer per collector
POST /v1/tenants/{tenant_id}/datasources/{datasource_id}/collect     ask the connector now
                                                                       {collectors?: [...]}

Who: anyone with metadata.read in the datasource's environment (like viewing it). Collectors
only read statistics and structure (never rows), so asking for them is not an audited change.
Collectors run in parallel; one failing does not stop the others (see `errors`).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError

from app.api.datasources import _RULE_ERRORS, _translate
from app.api.errors import conflict
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require_member
from app.gateway.hub import (
    ConnectorHub,
    ConnectorOfflineError,
    RequestTimeoutError,
    ToolFailedError,
    get_hub,
)
from app.models import Snapshot
from app.models.enums import Collector, DbEngine
from app.rbac.service import AccessContext
from app.schemas.snapshots import (
    DATA_MODELS,
    CollectError,
    CollectIn,
    HealthSnapshot,
    IndexesSnapshot,
    ServerSnapshotsOut,
    TableStatsSnapshot,
)
from app.services import datasources as datasources_svc
from app.services import snapshots as svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}/datasources", tags=["collectors"])

Member = Annotated[AccessContext, Depends(require_member)]

COLLECT_TIMEOUT_SECONDS = 45  # the connector gives each collector 30 s
SUPPORTED_ENGINES = {DbEngine.POSTGRES, DbEngine.MYSQL, DbEngine.MARIADB}
OUTDATED = "Update the connector to version 0.4.0 or newer to collect this."


def _out(
    datasource_id: uuid.UUID,
    latest: dict[Collector, Snapshot],
    errors: list[CollectError] | None = None,
) -> ServerSnapshotsOut:
    def pick(c: Collector) -> dict[str, Any] | None:
        s = latest.get(c)
        return None if s is None else {"collected_at": s.collected_at, "data": s.data}

    health, tables, indexes = (pick(c) for c in Collector)
    return ServerSnapshotsOut(
        datasource_id=datasource_id,
        health=None if health is None else HealthSnapshot.model_validate(health),
        table_stats=None if tables is None else TableStatsSnapshot.model_validate(tables),
        indexes=None if indexes is None else IndexesSnapshot.model_validate(indexes),
        errors=errors or [],
    )


async def _visible(
    session: DbSession, user: CurrentUser, tenant_id: uuid.UUID, datasource_id: uuid.UUID
) -> datasources_svc.DatasourceInfo:
    try:
        return await datasources_svc.get_visible(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None


@router.get("/{datasource_id}/snapshots")
async def latest_snapshots(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
) -> ServerSnapshotsOut:
    info = await _visible(session, user, tenant_id, datasource_id)
    return _out(info.datasource.id, await svc.latest(session, info.datasource.id))


@router.post("/{datasource_id}/collect")
async def collect_now(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    hub: Annotated[ConnectorHub, Depends(get_hub)],
    body: Annotated[CollectIn | None, Body()] = None,
) -> ServerSnapshotsOut:
    """Ask the connector to run collectors now (those that ran in the last 30 s are reused)."""
    info = await _visible(session, user, tenant_id, datasource_id)
    ds, connector = info.datasource, info.connector
    wanted = list(dict.fromkeys(body.collectors if body else list(Collector)))

    if ds.engine not in SUPPORTED_ENGINES:
        unsupported = [
            CollectError(
                collector=c, code="unsupported", message=f"Not available for {ds.engine} yet."
            )
            for c in wanted
        ]
        return _out(ds.id, await svc.latest(session, ds.id), unsupported)
    if not hub.is_online(connector.id):
        raise conflict(f"Connector {connector.name} is offline, so nothing can be collected now.")

    latest = await svc.latest(session, ds.id)
    now = datetime.now(UTC)
    todo = [c for c in wanted if not svc.is_fresh(latest.get(c), now)]

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
                return failed("outdated_connector", OUTDATED)
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
            latest[collector] = await svc.store(session, ds, collector, outcome)
    await session.commit()
    return _out(ds.id, latest, errors)
