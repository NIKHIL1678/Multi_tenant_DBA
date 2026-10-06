"""Environments of a company.

GET    /v1/tenants/{tenant_id}/environments                     needs metadata.read
GET    /v1/tenants/{tenant_id}/environments/{environment_id}    needs metadata.read
POST   /v1/tenants/{tenant_id}/environments                     needs datasources.manage
PATCH  /v1/tenants/{tenant_id}/environments/{environment_id}    needs datasources.manage (*)
DELETE /v1/tenants/{tenant_id}/environments/{environment_id}    needs datasources.manage (*)

(*) and org.manage when it touches a production environment's protection.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.errors import ApiError, conflict, forbidden, not_found
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require
from app.models import Environment
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext
from app.schemas.environments import EnvironmentCreateIn, EnvironmentOut, EnvironmentUpdateIn
from app.services import environments as svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}/environments", tags=["environments"])

CanRead = Annotated[AccessContext, Depends(require(Permission.METADATA_READ))]
CanManage = Annotated[AccessContext, Depends(require(Permission.DATASOURCES_MANAGE))]


def _out(env: Environment, datasource_count: int) -> EnvironmentOut:
    return EnvironmentOut(
        id=env.id,
        name=env.name,
        is_production=env.is_production,
        datasource_count=datasource_count,
        created_at=env.created_at,
    )


def _translate(exc: Exception) -> ApiError:
    if isinstance(exc, svc.EnvironmentNotFoundError):
        return not_found("Environment")
    if isinstance(exc, svc.NameTakenError):
        return conflict("An environment with this name already exists.")
    if isinstance(exc, svc.NeedsOrgManageError):
        return forbidden("Only an Owner can remove protection from a production environment.")
    if isinstance(exc, svc.NotEmptyError):
        return conflict(
            f"This environment still has {exc.datasources} database(s). Move or remove them first."
        )
    raise exc


_RULE_ERRORS = (
    svc.EnvironmentNotFoundError,
    svc.NameTakenError,
    svc.NeedsOrgManageError,
    svc.NotEmptyError,
)


@router.get("")
async def list_environments(
    tenant_id: uuid.UUID, _: CanRead, session: DbSession
) -> list[EnvironmentOut]:
    return [
        _out(i.environment, i.datasource_count)
        for i in await svc.list_environments(session, tenant_id)
    ]


@router.get("/{environment_id}")
async def get_environment(
    tenant_id: uuid.UUID, environment_id: uuid.UUID, _: CanRead, session: DbSession
) -> EnvironmentOut:
    try:
        info = await svc.get_environment(session, tenant_id, environment_id)
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None
    return _out(info.environment, info.datasource_count)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_environment(
    tenant_id: uuid.UUID,
    body: EnvironmentCreateIn,
    _: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> EnvironmentOut:
    try:
        env = await svc.create_environment(
            session, tenant_id=tenant_id, name=body.name, is_production=body.is_production
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="environment.created",
        target_type="environment",
        target_id=env.id,
        details={"name": env.name, "is_production": env.is_production},
        request=request,
    )
    await session.commit()
    return _out(env, 0)


@router.patch("/{environment_id}")
async def update_environment(
    tenant_id: uuid.UUID,
    environment_id: uuid.UUID,
    body: EnvironmentUpdateIn,
    access: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> EnvironmentOut:
    try:
        info, changes = await svc.update_environment(
            session,
            tenant_id=tenant_id,
            environment_id=environment_id,
            actor_permissions=access.permissions,
            name=body.name,
            is_production=body.is_production,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    if changes:
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action="environment.updated",
            target_type="environment",
            target_id=environment_id,
            details=changes,
            request=request,
        )
        await session.commit()
    return _out(info.environment, info.datasource_count)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    tenant_id: uuid.UUID,
    environment_id: uuid.UUID,
    access: CanManage,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    try:
        env = await svc.delete_environment(
            session,
            tenant_id=tenant_id,
            environment_id=environment_id,
            actor_permissions=access.permissions,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="environment.deleted",
        target_type="environment",
        target_id=environment_id,
        details={"name": env.name, "is_production": env.is_production},
        request=request,
    )
    await session.commit()
