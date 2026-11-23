"""Collectors: read-only statistics about one datasource, gathered by its connector.

GET  /v1/tenants/{tenant_id}/datasources/{datasource_id}/snapshots   latest answer per collector
POST /v1/tenants/{tenant_id}/datasources/{datasource_id}/collect     ask the connector now
                                                                       {collectors?: [...]}

Who: anyone with metadata.read in the datasource's environment (like viewing it). Collectors
only read statistics and structure (never rows), so asking for them is not an audited change.
Collectors run in parallel; one failing does not stop the others (see `errors`).
By default the collectors the server page shows run (PAGE_COLLECTORS); table_index runs only
when asked for, and its (large) answer is kept for search, not returned here.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from app.api.datasources import _RULE_ERRORS, _translate
from app.api.errors import conflict
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require_member
from app.gateway.hub import ConnectorHub, get_hub
from app.models import Snapshot
from app.models.enums import Collector
from app.rbac.service import AccessContext
from app.schemas.snapshots import (
    PAGE_COLLECTORS,
    CollectError,
    CollectIn,
    HealthSnapshot,
    IndexesSnapshot,
    LocksSnapshot,
    ServerSnapshotsOut,
    SlowQueriesSnapshot,
    TableStatsSnapshot,
)
from app.services import collect as collect_svc
from app.services import datasources as datasources_svc
from app.services import snapshots as svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}/datasources", tags=["collectors"])

Member = Annotated[AccessContext, Depends(require_member)]


def _out(
    datasource_id: uuid.UUID,
    latest: dict[Collector, Snapshot],
    errors: list[CollectError] | None = None,
) -> ServerSnapshotsOut:
    def pick(c: Collector) -> dict[str, Any] | None:
        s = latest.get(c)
        return None if s is None else {"collected_at": s.collected_at, "data": s.data}

    health, tables, indexes, slow, locks = (pick(c) for c in PAGE_COLLECTORS)
    return ServerSnapshotsOut(
        datasource_id=datasource_id,
        health=None if health is None else HealthSnapshot.model_validate(health),
        table_stats=None if tables is None else TableStatsSnapshot.model_validate(tables),
        indexes=None if indexes is None else IndexesSnapshot.model_validate(indexes),
        slow_queries=None if slow is None else SlowQueriesSnapshot.model_validate(slow),
        locks=None if locks is None else LocksSnapshot.model_validate(locks),
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
    return _out(info.datasource.id, await svc.latest(session, info.datasource.id, PAGE_COLLECTORS))


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
    """Ask the connector to run collectors now (those that ran very recently are reused)."""
    info = await _visible(session, user, tenant_id, datasource_id)
    ds, connector = info.datasource, info.connector
    wanted = list(dict.fromkeys(body.collectors if body else PAGE_COLLECTORS))

    if ds.engine not in collect_svc.SUPPORTED_ENGINES:
        errors = collect_svc.unsupported(ds, wanted)
        return _out(ds.id, await svc.latest(session, ds.id, PAGE_COLLECTORS), errors)
    if not hub.is_online(connector.id):
        raise conflict(f"Connector {connector.name} is offline, so nothing can be collected now.")

    errors = await collect_svc.collect(session, hub, ds, connector, wanted)
    return _out(ds.id, await svc.latest(session, ds.id, PAGE_COLLECTORS), errors)
