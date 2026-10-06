"""Invitations: how a new person joins a company.

Flow:
1. A member with `members.manage` invites an email with a role. They get a one-time token
   (shown once; only its SHA-256 hash is stored).
2. The invited person opens the link, signs up or signs in with THAT email, and accepts.
3. Accepting creates the membership and marks the invitation used.

Rules:
- Same no-escalation rule as role changes: you can only invite with a role you could grant.
- Someone who is already a member (active or suspended) cannot be invited again.
- Inviting an email that already has a pending invitation replaces it (old link stops working).
- Links expire after INVITATION_DAYS.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invitation, Role, Tenant, TenantMember, User
from app.models.enums import TenantStatus
from app.services.members import RoleInfo, check_can_manage, get_role

INVITATION_DAYS = 7


class AlreadyMemberError(Exception):
    pass


class InvitationNotFoundError(Exception):
    pass


class WrongEmailError(Exception):
    pass


@dataclass(slots=True)
class InvitationInfo:
    invitation: Invitation
    role: Role
    invited_by: User | None


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _pending(now: datetime) -> list[ColumnElement[bool]]:
    return [
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > now,
    ]


async def _is_member(session: AsyncSession, tenant_id: uuid.UUID, email: str) -> bool:
    found = await session.scalar(
        select(TenantMember.id)
        .join(User, User.id == TenantMember.user_id)
        .where(TenantMember.tenant_id == tenant_id, User.email == email)
    )
    return found is not None


async def create_invitation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    role_id: uuid.UUID,
    invited_by: uuid.UUID,
    actor_permissions: frozenset[str],
) -> tuple[Invitation, RoleInfo, str, int]:
    """Returns (invitation, role, raw token, number of older invitations it replaced)."""
    role = await get_role(session, tenant_id, role_id)
    check_can_manage(actor_permissions, role.permissions)
    if await _is_member(session, tenant_id, email):
        raise AlreadyMemberError

    now = datetime.now(UTC)
    replaced = await session.execute(
        update(Invitation)
        .where(Invitation.tenant_id == tenant_id, Invitation.email == email, *_pending(now))
        .values(revoked_at=now)
    )
    raw = secrets.token_urlsafe(32)
    invitation = Invitation(
        tenant_id=tenant_id,
        email=email,
        role_id=role.role.id,
        token_hash=_hash(raw),
        invited_by=invited_by,
        expires_at=now + timedelta(days=INVITATION_DAYS),
    )
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return invitation, role, raw, replaced.rowcount or 0  # type: ignore[attr-defined]


async def list_pending(session: AsyncSession, tenant_id: uuid.UUID) -> list[InvitationInfo]:
    rows = await session.execute(
        select(Invitation, Role, User)
        .join(Role, Role.id == Invitation.role_id)
        .outerjoin(User, User.id == Invitation.invited_by)
        .where(Invitation.tenant_id == tenant_id, *_pending(datetime.now(UTC)))
        .order_by(Invitation.created_at.desc())
    )
    return [InvitationInfo(invitation=i, role=r, invited_by=u) for i, r, u in rows.all()]


async def revoke_invitation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    actor_permissions: frozenset[str],
) -> Invitation:
    invitation = await session.scalar(
        select(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.tenant_id == tenant_id,
            *_pending(datetime.now(UTC)),
        )
        .with_for_update()
    )
    if invitation is None:
        raise InvitationNotFoundError
    role = await get_role(session, tenant_id, invitation.role_id)
    check_can_manage(actor_permissions, role.permissions)
    invitation.revoked_at = datetime.now(UTC)
    await session.flush()
    return invitation


async def _by_token(
    session: AsyncSession, raw: str, *, lock: bool = False
) -> tuple[Invitation, Tenant, Role, User | None]:
    query = (
        select(Invitation, Tenant, Role, User)
        .join(Tenant, Tenant.id == Invitation.tenant_id)
        .join(Role, Role.id == Invitation.role_id)
        .outerjoin(User, User.id == Invitation.invited_by)
        .where(
            Invitation.token_hash == _hash(raw),
            Tenant.status == TenantStatus.ACTIVE,
            *_pending(datetime.now(UTC)),
        )
    )
    if lock:
        query = query.with_for_update(of=Invitation)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise InvitationNotFoundError
    return row[0], row[1], row[2], row[3]


async def preview(session: AsyncSession, raw: str) -> tuple[Invitation, Tenant, Role, User | None]:
    """What the invite page shows before the person signs in."""
    return await _by_token(session, raw)


async def accept(
    session: AsyncSession, *, raw: str, user_id: uuid.UUID, user_email: str
) -> tuple[Invitation, Tenant, Role, TenantMember]:
    invitation, tenant, role, _ = await _by_token(session, raw, lock=True)
    if user_email.lower() != invitation.email.lower():
        raise WrongEmailError
    if await _is_member(session, tenant.id, user_email):
        raise AlreadyMemberError

    member = TenantMember(
        tenant_id=tenant.id,
        user_id=user_id,
        role_id=invitation.role_id,
        invited_by=invitation.invited_by,
    )
    session.add(member)
    invitation.accepted_at = datetime.now(UTC)
    await session.flush()
    return invitation, tenant, role, member
