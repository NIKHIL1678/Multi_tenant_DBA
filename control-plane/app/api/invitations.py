"""Invitations.

Company side (needs members.manage):
POST   /v1/tenants/{tenant_id}/invitations                    invite an email with a role
GET    /v1/tenants/{tenant_id}/invitations                    pending invitations
DELETE /v1/tenants/{tenant_id}/invitations/{invitation_id}    cancel one

Invited person:
POST   /v1/invitations/preview   {token}   who invited me, to what (no sign-in needed)
POST   /v1/invitations/accept    {token}   join the company (signed in with the invited email)
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.errors import ApiError, conflict, forbidden, not_found
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require
from app.core.logging import tenant_id_var
from app.models import Invitation, Role
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext
from app.schemas.invitations import (
    InvitationAcceptedOut,
    InvitationCreatedOut,
    InvitationCreateIn,
    InvitationOut,
    InvitationPreviewOut,
    InvitationTokenIn,
)
from app.schemas.members import RoleRef
from app.services import invitations as svc
from app.services import members as members_svc

tenant_router = APIRouter(prefix="/v1/tenants/{tenant_id}/invitations", tags=["invitations"])
public_router = APIRouter(prefix="/v1/invitations", tags=["invitations"])

CanManageMembers = Annotated[AccessContext, Depends(require(Permission.MEMBERS_MANAGE))]

_LINK_INVALID = "This invitation link is invalid, expired or already used."


def _out(inv: Invitation, role: Role, invited_by_email: str | None) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=RoleRef(id=role.id, key=role.key, name=role.name),
        invited_by_email=invited_by_email,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


def _translate(exc: Exception) -> ApiError:
    if isinstance(exc, members_svc.RoleNotFoundError):
        return ApiError(422, "invalid_role", "That role does not exist in this company.")
    if isinstance(exc, members_svc.EscalationError):
        return forbidden("You cannot invite with a role that has more access than your own.")
    if isinstance(exc, svc.AlreadyMemberError):
        return conflict("This person is already a member of the company.")
    if isinstance(exc, svc.InvitationNotFoundError):
        return not_found("Invitation")
    if isinstance(exc, svc.WrongEmailError):
        return forbidden("This invitation was sent to a different email address.")
    raise exc


_RULE_ERRORS = (
    members_svc.RoleNotFoundError,
    members_svc.EscalationError,
    svc.AlreadyMemberError,
    svc.InvitationNotFoundError,
    svc.WrongEmailError,
)


# ---- company side -----------------------------------------------------------------------------


@tenant_router.post("", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    tenant_id: uuid.UUID,
    body: InvitationCreateIn,
    access: CanManageMembers,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> InvitationCreatedOut:
    email = str(body.email).lower()
    try:
        inv, role, token, replaced = await svc.create_invitation(
            session,
            tenant_id=tenant_id,
            email=email,
            role_id=body.role_id,
            invited_by=user.user_id,
            actor_permissions=access.permissions,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="invitation.created",
        target_type="invitation",
        target_id=inv.id,
        details={"email": email, "role": role.role.key, "replaced": replaced},
        request=request,
    )
    await session.commit()
    return InvitationCreatedOut(**_out(inv, role.role, user.email).model_dump(), token=token)


@tenant_router.get("")
async def list_invitations(
    tenant_id: uuid.UUID, _: CanManageMembers, session: DbSession
) -> list[InvitationOut]:
    return [
        _out(i.invitation, i.role, i.invited_by.email if i.invited_by else None)
        for i in await svc.list_pending(session, tenant_id)
    ]


@tenant_router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    access: CanManageMembers,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    try:
        inv = await svc.revoke_invitation(
            session,
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            actor_permissions=access.permissions,
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    await record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.user_id,
        action="invitation.revoked",
        target_type="invitation",
        target_id=inv.id,
        details={"email": inv.email},
        request=request,
    )
    await session.commit()


# ---- invited person ---------------------------------------------------------------------------


@public_router.post("/preview")
async def preview_invitation(body: InvitationTokenIn, session: DbSession) -> InvitationPreviewOut:
    try:
        inv, tenant, role, inviter = await svc.preview(session, body.token)
    except svc.InvitationNotFoundError:
        raise ApiError(404, "invitation_invalid", _LINK_INVALID) from None
    return InvitationPreviewOut(
        tenant_name=tenant.name,
        role_name=role.name,
        email=inv.email,
        invited_by_name=(inviter.full_name or inviter.email) if inviter else None,
        expires_at=inv.expires_at,
    )


@public_router.post("/accept")
async def accept_invitation(
    body: InvitationTokenIn, user: CurrentUser, session: DbSession, request: Request
) -> InvitationAcceptedOut:
    try:
        inv, tenant, role, member = await svc.accept(
            session, raw=body.token, user_id=user.user_id, user_email=user.email
        )
    except svc.InvitationNotFoundError:
        raise ApiError(404, "invitation_invalid", _LINK_INVALID) from None
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None

    tenant_id_var.set(str(tenant.id))
    await record_audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.user_id,
        action="invitation.accepted",
        target_type="member",
        target_id=member.id,
        details={"email": inv.email, "role": role.key, "invitation_id": str(inv.id)},
        request=request,
    )
    await session.commit()
    return InvitationAcceptedOut(tenant_id=tenant.id, tenant_name=tenant.name, role_key=role.key)
