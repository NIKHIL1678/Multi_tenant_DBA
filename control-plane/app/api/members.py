"""Members and roles of a company.

GET    /v1/tenants/{tenant_id}/roles                                     needs metadata.read
GET    /v1/tenants/{tenant_id}/members                                   needs metadata.read
GET    /v1/tenants/{tenant_id}/members/{member_id}                       needs metadata.read
PATCH  /v1/tenants/{tenant_id}/members/{member_id}                       needs members.manage
PUT    /v1/tenants/{tenant_id}/members/{member_id}/environments/{env_id} needs members.manage
DELETE /v1/tenants/{tenant_id}/members/{member_id}/environments/{env_id} needs members.manage
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.errors import ApiError, conflict, forbidden, not_found
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require
from app.models import Role
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext
from app.schemas.members import (
    EnvironmentRoleIn,
    EnvironmentRoleOut,
    MemberOut,
    MemberUpdateIn,
    RoleOut,
    RoleRef,
)
from app.services import members as svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["members"])

CanRead = Annotated[AccessContext, Depends(require(Permission.METADATA_READ))]
CanManageMembers = Annotated[AccessContext, Depends(require(Permission.MEMBERS_MANAGE))]


def _ref(role: Role) -> RoleRef:
    return RoleRef(id=role.id, key=role.key, name=role.name)


def _member_out(info: svc.MemberInfo) -> MemberOut:
    return MemberOut(
        id=info.member.id,
        user_id=info.user.id,
        email=info.user.email,
        full_name=info.user.full_name,
        role=_ref(info.role),
        status=info.member.status,
        joined_at=info.member.joined_at,
        environment_roles=[
            EnvironmentRoleOut(
                environment_id=er.environment_id,
                environment_name=er.environment_name,
                role=_ref(er.role),
            )
            for er in info.environment_roles
        ],
    )


def _translate(exc: Exception) -> ApiError:
    """Turn a business-rule error into the right HTTP answer."""
    if isinstance(exc, svc.MemberNotFoundError):
        return not_found("Member")
    if isinstance(exc, svc.EnvironmentNotFoundError):
        return not_found("Environment")
    if isinstance(exc, svc.RoleNotFoundError):
        return ApiError(422, "invalid_role", "That role does not exist in this company.")
    if isinstance(exc, svc.EscalationError):
        return forbidden("You cannot manage a role with more access than your own.")
    if isinstance(exc, svc.LastOwnerError):
        return conflict("A company must keep at least one active Owner.")
    if isinstance(exc, svc.SelfSuspendError):
        return conflict("You cannot suspend yourself.")
    raise exc


_RULE_ERRORS = (
    svc.MemberNotFoundError,
    svc.EnvironmentNotFoundError,
    svc.RoleNotFoundError,
    svc.EscalationError,
    svc.LastOwnerError,
    svc.SelfSuspendError,
)


@router.get("/roles")
async def list_roles(tenant_id: uuid.UUID, _: CanRead, session: DbSession) -> list[RoleOut]:
    return [
        RoleOut(
            id=ri.role.id,
            key=ri.role.key,
            name=ri.role.name,
            is_system=ri.role.is_system,
            permissions=sorted(ri.permissions),
        )
        for ri in await svc.list_roles(session, tenant_id)
    ]


@router.get("/members")
async def list_members(tenant_id: uuid.UUID, _: CanRead, session: DbSession) -> list[MemberOut]:
    return [_member_out(info) for info in await svc.list_members(session, tenant_id)]


@router.get("/members/{member_id}")
async def get_member(
    tenant_id: uuid.UUID, member_id: uuid.UUID, _: CanRead, session: DbSession
) -> MemberOut:
    try:
        return _member_out(await svc.get_member(session, tenant_id, member_id))
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None


@router.patch("/members/{member_id}")
async def update_member(
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    body: MemberUpdateIn,
    access: CanManageMembers,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> MemberOut:
    try:
        info, changes = await svc.update_member(
            session,
            tenant_id=tenant_id,
            member_id=member_id,
            actor_user_id=user.user_id,
            actor_permissions=access.permissions,
            role_id=body.role_id,
            status=body.status,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    for what, change in changes.items():
        action = {
            "role": "member.role_changed",
            "status": "member.suspended" if change["to"] == "suspended" else "member.reactivated",
        }[what]
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action=action,
            target_type="member",
            target_id=member_id,
            details={"email": info.user.email, **change},
            request=request,
        )
    await session.commit()
    return _member_out(info)


@router.put("/members/{member_id}/environments/{environment_id}")
async def set_environment_role(
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    environment_id: uuid.UUID,
    body: EnvironmentRoleIn,
    access: CanManageMembers,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> MemberOut:
    try:
        env_name, previous, new_key = await svc.set_environment_role(
            session,
            tenant_id=tenant_id,
            member_id=member_id,
            environment_id=environment_id,
            role_id=body.role_id,
            actor_permissions=access.permissions,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    if previous != new_key:
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action="member.environment_role_set",
            target_type="member",
            target_id=member_id,
            details={"environment": env_name, "from": previous, "to": new_key},
            request=request,
        )
    await session.commit()
    return _member_out(await svc.get_member(session, tenant_id, member_id))


@router.delete(
    "/members/{member_id}/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_environment_role(
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    environment_id: uuid.UUID,
    access: CanManageMembers,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    try:
        old_key = await svc.remove_environment_role(
            session,
            tenant_id=tenant_id,
            member_id=member_id,
            environment_id=environment_id,
            actor_permissions=access.permissions,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="member.environment_role_removed",
        target_type="member",
        target_id=member_id,
        details={"environment_id": str(environment_id), "from": old_key},
        request=request,
    )
    await session.commit()
