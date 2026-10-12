"""Connectors.

Dashboard side:
GET    /v1/tenants/{tenant_id}/connectors                                    needs metadata.read
GET    /v1/tenants/{tenant_id}/connectors/{connector_id}                     needs metadata.read
POST   /v1/tenants/{tenant_id}/connectors                  create + command  needs connectors.manage
POST   /v1/tenants/{tenant_id}/connectors/{id}/enrollment-token   new command  connectors.manage
PATCH  /v1/tenants/{tenant_id}/connectors/{connector_id}   rename           needs connectors.manage
POST   /v1/tenants/{tenant_id}/connectors/{connector_id}/revoke              needs connectors.manage

Connector program side (no user, the one-time token is the proof):
POST   /v1/connectors/enroll    {token, public_key, version}
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.errors import ApiError, conflict, not_found
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require
from app.core.logging import tenant_id_var
from app.gateway.hub import ConnectorHub, get_hub
from app.gateway.protocol import CloseCode
from app.models.enums import ActorType
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext
from app.schemas.connectors import (
    ConnectorCreatedOut,
    ConnectorCreateIn,
    ConnectorOut,
    ConnectorUpdateIn,
    EnrollIn,
    EnrollmentOut,
    EnrollOut,
)
from app.services import connectors as svc

tenant_router = APIRouter(prefix="/v1/tenants/{tenant_id}/connectors", tags=["connectors"])
public_router = APIRouter(prefix="/v1/connectors", tags=["connectors"])

CanRead = Annotated[AccessContext, Depends(require(Permission.METADATA_READ))]
CanManage = Annotated[AccessContext, Depends(require(Permission.CONNECTORS_MANAGE))]


def _out(info: svc.ConnectorInfo) -> ConnectorOut:
    c = info.connector
    return ConnectorOut(
        id=c.id,
        name=c.name,
        status=c.status,
        version=c.version,
        last_seen_at=c.last_seen_at,
        datasource_count=info.datasource_count,
        enrollment_expires_at=info.enrollment_expires_at,
        created_at=c.created_at,
        revoked_at=c.revoked_at,
    )


def _enrollment(issued: svc.IssuedToken) -> EnrollmentOut:
    return EnrollmentOut(token=issued.token, expires_at=issued.expires_at, command=issued.command)


def _translate(exc: Exception) -> ApiError:
    if isinstance(exc, svc.ConnectorNotFoundError):
        return not_found("Connector")
    if isinstance(exc, svc.NameTakenError):
        return conflict("A connector with this name already exists.")
    if isinstance(exc, svc.NotPendingError):
        return conflict("This connector is already installed or revoked.")
    if isinstance(exc, svc.AlreadyRevokedError):
        return conflict("This connector is already revoked.")
    raise exc


_RULE_ERRORS = (
    svc.ConnectorNotFoundError,
    svc.NameTakenError,
    svc.NotPendingError,
    svc.AlreadyRevokedError,
)


# ---- dashboard side ----------------------------------------------------------------------------


@tenant_router.get("")
async def list_connectors(
    tenant_id: uuid.UUID, _: CanRead, session: DbSession
) -> list[ConnectorOut]:
    return [_out(i) for i in await svc.list_connectors(session, tenant_id)]


@tenant_router.get("/{connector_id}")
async def get_connector(
    tenant_id: uuid.UUID, connector_id: uuid.UUID, _: CanRead, session: DbSession
) -> ConnectorOut:
    try:
        return _out(await svc.get_connector(session, tenant_id, connector_id))
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None


@tenant_router.post("", status_code=status.HTTP_201_CREATED)
async def create_connector(
    tenant_id: uuid.UUID,
    body: ConnectorCreateIn,
    _: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> ConnectorCreatedOut:
    try:
        connector, issued = await svc.create_connector(
            session, tenant_id=tenant_id, name=body.name, created_by=user.user_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="connector.created",
        target_type="connector",
        target_id=connector.id,
        details={"name": connector.name},  # never the token
        request=request,
    )
    await session.commit()
    info = svc.ConnectorInfo(connector, 0, issued.expires_at)
    return ConnectorCreatedOut(connector=_out(info), enrollment=_enrollment(issued))


@tenant_router.post("/{connector_id}/enrollment-token", status_code=status.HTTP_201_CREATED)
async def new_enrollment_token(
    tenant_id: uuid.UUID,
    connector_id: uuid.UUID,
    _: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> EnrollmentOut:
    try:
        connector, issued = await svc.new_enrollment_token(
            session, tenant_id=tenant_id, connector_id=connector_id, created_by=user.user_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="connector.token_issued",
        target_type="connector",
        target_id=connector.id,
        details={"name": connector.name},
        request=request,
    )
    await session.commit()
    return _enrollment(issued)


@tenant_router.patch("/{connector_id}")
async def rename_connector(
    tenant_id: uuid.UUID,
    connector_id: uuid.UUID,
    body: ConnectorUpdateIn,
    _: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> ConnectorOut:
    try:
        info, old = await svc.rename_connector(
            session, tenant_id=tenant_id, connector_id=connector_id, name=body.name
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    if old is not None:
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action="connector.renamed",
            target_type="connector",
            target_id=connector_id,
            details={"from": old, "to": body.name},
            request=request,
        )
        await session.commit()
    return _out(info)


@tenant_router.post("/{connector_id}/revoke")
async def revoke_connector(
    tenant_id: uuid.UUID,
    connector_id: uuid.UUID,
    _: CanManage,
    user: CurrentUser,
    hub: Annotated[ConnectorHub, Depends(get_hub)],
    session: DbSession,
    request: Request,
) -> ConnectorOut:
    try:
        info = await svc.revoke_connector(session, tenant_id=tenant_id, connector_id=connector_id)
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="connector.revoked",
        target_type="connector",
        target_id=connector_id,
        details={"name": info.connector.name, "datasources": info.datasource_count},
        request=request,
    )
    await session.commit()
    # Its key is erased; also drop the live link now instead of waiting for the next handshake.
    await hub.disconnect(connector_id, CloseCode.REVOKED, "revoked")
    return _out(info)


# ---- connector program side --------------------------------------------------------------------


@public_router.post("/enroll")
async def enroll(body: EnrollIn, session: DbSession, request: Request) -> EnrollOut:
    try:
        connector = await svc.enroll(
            session, raw_token=body.token, public_key=body.public_key, version=body.version
        )
    except svc.EnrollmentInvalidError:
        # One answer for unknown, expired, used or revoked: gives an attacker nothing to learn.
        raise ApiError(
            401, "enrollment_invalid", "This install command is invalid, expired or already used."
        ) from None

    tenant_id_var.set(str(connector.tenant_id))
    await record_audit(
        session,
        tenant_id=connector.tenant_id,
        actor_type=ActorType.CONNECTOR,
        actor_id=connector.id,
        action="connector.enrolled",
        target_type="connector",
        target_id=connector.id,
        details={"name": connector.name, "version": body.version},
        request=request,
    )
    await session.commit()
    return EnrollOut(connector_id=connector.id, tenant_id=connector.tenant_id)
