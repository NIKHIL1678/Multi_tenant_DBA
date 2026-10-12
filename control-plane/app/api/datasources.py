"""Datasources (the customer's databases).

GET    /v1/tenants/{tenant_id}/datasources                 filters: environment_id, connector_id,
                                                           engine, status
GET    /v1/tenants/{tenant_id}/datasources/{datasource_id}
GET    /v1/tenants/{tenant_id}/datasources/{datasource_id}/databases   every database on that server
PATCH  /v1/tenants/{tenant_id}/datasources/{datasource_id}  {environment_id}  move
DELETE /v1/tenants/{tenant_id}/datasources/{datasource_id}
POST   /v1/tenants/{tenant_id}/datasources/{datasource_id}/check   ask its connector to test it now

Permissions are checked PER ENVIRONMENT (overrides apply), not just company-wide:
- see:    metadata.read in the datasource's environment (otherwise it looks like it doesn't exist)
- change: datasources.manage there (and in the target environment when moving)
- taking it out of production: also org.manage
New datasources are not created here: connectors report them (see services.datasources).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.errors import ApiError, conflict, forbidden, not_found
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require_member
from app.gateway.hub import (
    ConnectorHub,
    ConnectorOfflineError,
    RequestTimeoutError,
    ToolFailedError,
    get_hub,
)
from app.models import Datasource
from app.models.enums import DatasourceStatus, DbEngine
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext, environments_with_permission
from app.schemas.datasources import (
    CatalogDatabase,
    CatalogSummary,
    ConnectorRef,
    DatasourceCatalogOut,
    DatasourceMoveIn,
    DatasourceOut,
    EnvironmentRef,
    ReportedDatasource,
)
from app.services import datasources as svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}/datasources", tags=["datasources"])

Member = Annotated[AccessContext, Depends(require_member)]

CHECK_TIMEOUT_SECONDS = 30


def _catalog_entries(raw: dict[str, Any] | None) -> list[CatalogDatabase]:
    if not raw:
        return []
    return [CatalogDatabase.model_validate(d) for d in raw.get("databases", [])]


def _summary(d: Datasource) -> CatalogSummary | None:
    if d.catalog is None or d.catalog_updated_at is None:
        return None
    entries = _catalog_entries(d.catalog)
    sizes = [e.size_bytes for e in entries if e.size_bytes is not None]
    return CatalogSummary(
        database_count=len(entries),
        total_size_bytes=sum(sizes) if sizes else None,
        truncated=bool(d.catalog.get("truncated", False)),
        updated_at=d.catalog_updated_at,
    )


def _out(info: svc.DatasourceInfo) -> DatasourceOut:
    d, c, e = info.datasource, info.connector, info.environment
    return DatasourceOut(
        id=d.id,
        local_name=d.local_name,
        engine=d.engine,
        version=d.version,
        status=d.status,
        capabilities=d.capabilities,
        last_checked_at=d.last_checked_at,
        catalog=_summary(d),
        connector=ConnectorRef(id=c.id, name=c.name, status=c.status),
        environment=EnvironmentRef(id=e.id, name=e.name, is_production=e.is_production),
        created_at=d.created_at,
    )


def _translate(exc: Exception) -> ApiError:
    if isinstance(exc, svc.DatasourceNotFoundError):
        return not_found("Datasource")
    if isinstance(exc, svc.EnvironmentNotFoundError):
        return not_found("Environment")
    if isinstance(exc, svc.NotAllowedError):
        return forbidden("You cannot manage databases in this environment.")
    if isinstance(exc, svc.NeedsOrgManageError):
        return forbidden("Only an Owner can take a database out of production.")
    raise exc


_RULE_ERRORS = (
    svc.DatasourceNotFoundError,
    svc.EnvironmentNotFoundError,
    svc.NotAllowedError,
    svc.NeedsOrgManageError,
)


@router.get("")
async def list_datasources(
    tenant_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    environment_id: uuid.UUID | None = None,
    connector_id: uuid.UUID | None = None,
    engine: Annotated[DbEngine | None, Query()] = None,
    status: Annotated[DatasourceStatus | None, Query()] = None,
) -> list[DatasourceOut]:
    visible = await environments_with_permission(
        session, user_id=user.user_id, tenant_id=tenant_id, permission=Permission.METADATA_READ
    )
    infos = await svc.list_datasources(
        session,
        tenant_id=tenant_id,
        visible_environments=visible,
        environment_id=environment_id,
        connector_id=connector_id,
        engine=engine,
        status=status,
    )
    return [_out(i) for i in infos]


@router.get("/{datasource_id}")
async def get_datasource(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
) -> DatasourceOut:
    try:
        info = await svc.get_visible(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None
    return _out(info)


@router.get("/{datasource_id}/databases")
async def list_server_databases(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
) -> DatasourceCatalogOut:
    """The databases on this server as last reported (biggest first). Names and sizes only."""
    try:
        info = await svc.get_visible(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None
    d = info.datasource
    return DatasourceCatalogOut(
        datasource_id=d.id,
        updated_at=d.catalog_updated_at,
        truncated=bool((d.catalog or {}).get("truncated", False)),
        databases=_catalog_entries(d.catalog),
    )


@router.patch("/{datasource_id}")
async def move_datasource(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    body: DatasourceMoveIn,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> DatasourceOut:
    try:
        info, source = await svc.move_datasource(
            session,
            user_id=user.user_id,
            tenant_id=tenant_id,
            datasource_id=datasource_id,
            environment_id=body.environment_id,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    if source is not None:
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action="datasource.moved",
            target_type="datasource",
            target_id=datasource_id,
            details={
                "name": info.datasource.local_name,
                "from": source.name,
                "to": info.environment.name,
            },
            request=request,
        )
        await session.commit()
    return _out(info)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    try:
        info = await svc.delete_datasource(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="datasource.deleted",
        target_type="datasource",
        target_id=datasource_id,
        details={
            "name": info.datasource.local_name,
            "engine": info.datasource.engine,
            "environment": info.environment.name,
            "connector": info.connector.name,
        },
        request=request,
    )
    await session.commit()


@router.post("/{datasource_id}/check")
async def check_datasource(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    hub: Annotated[ConnectorHub, Depends(get_hub)],
) -> DatasourceOut:
    """Ask the database's connector to test it right now (read-only; needs metadata.read there)."""
    try:
        info = await svc.get_visible(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    try:
        result = await hub.request(
            info.connector.id,
            "probe",
            {"datasource": info.datasource.local_name},
            wait_seconds=CHECK_TIMEOUT_SECONDS,
        )
        report = ReportedDatasource.model_validate(result)
        await svc.apply_check(session, info, report)
    except ConnectorOfflineError:
        raise conflict(
            f"Connector {info.connector.name} is offline, so this database cannot be checked now."
        ) from None
    except RequestTimeoutError:
        raise ApiError(504, "connector_timeout", "The connector did not answer in time.") from None
    except ToolFailedError as exc:
        raise ApiError(502, "connector_error", exc.message) from None
    except (ValueError, svc.CheckMismatchError):
        raise ApiError(502, "connector_error", "The connector sent an unexpected answer.") from None

    await session.commit()
    return _out(info)
