"""Members and roles: who is in a company and what they may do.

Safety rules (enforced here, not in the UI):
1. No escalation: you can only give a role whose permissions you already have yourself.
2. No managing "above" you: you cannot change a member whose role has permissions you lack
   (an IT Admin cannot demote an Owner or a DBA).
3. A company always keeps at least one active Owner.
4. You cannot suspend yourself.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Environment, MemberEnvironmentRole, Role, RolePermission, TenantMember, User
from app.models.enums import MemberStatus
from app.rbac.catalog import SystemRole, system_role_id

OWNER_ROLE_ID = system_role_id(SystemRole.OWNER)


class MemberNotFoundError(Exception):
    pass


class EnvironmentNotFoundError(Exception):
    pass


class RoleNotFoundError(Exception):
    pass


class EscalationError(Exception):
    pass


class LastOwnerError(Exception):
    pass


class SelfSuspendError(Exception):
    pass


@dataclass(slots=True)
class RoleInfo:
    role: Role
    permissions: frozenset[str]


@dataclass(slots=True)
class EnvRole:
    environment_id: uuid.UUID
    environment_name: str
    role: Role


@dataclass(slots=True)
class MemberInfo:
    member: TenantMember
    user: User
    role: Role
    environment_roles: list[EnvRole] = field(default_factory=list)


# ---- roles ---------------------------------------------------------------------------------


async def _permissions_by_role(
    session: AsyncSession, role_ids: set[uuid.UUID]
) -> dict[uuid.UUID, frozenset[str]]:
    perms: dict[uuid.UUID, set[str]] = defaultdict(set)
    if role_ids:
        rows = await session.execute(
            select(RolePermission.role_id, RolePermission.permission_key).where(
                RolePermission.role_id.in_(role_ids)
            )
        )
        for rid, key in rows.all():
            perms[rid].add(key)
    return {rid: frozenset(perms[rid]) for rid in role_ids}


async def list_roles(session: AsyncSession, tenant_id: uuid.UUID) -> list[RoleInfo]:
    """System roles plus this company's custom roles."""
    roles = (
        await session.scalars(
            select(Role)
            .where(or_(Role.tenant_id.is_(None), Role.tenant_id == tenant_id))
            .order_by(Role.is_system.desc(), Role.name)
        )
    ).all()
    perms = await _permissions_by_role(session, {r.id for r in roles})
    return [RoleInfo(role=r, permissions=perms[r.id]) for r in roles]


async def get_role(session: AsyncSession, tenant_id: uuid.UUID, role_id: uuid.UUID) -> RoleInfo:
    """A role usable in this company. Another company's custom role does not exist here."""
    role = await session.scalar(
        select(Role).where(
            Role.id == role_id, or_(Role.tenant_id.is_(None), Role.tenant_id == tenant_id)
        )
    )
    if role is None:
        raise RoleNotFoundError
    perms = await _permissions_by_role(session, {role.id})
    return RoleInfo(role=role, permissions=perms[role.id])


# ---- members -------------------------------------------------------------------------------


async def list_members(
    session: AsyncSession, tenant_id: uuid.UUID, member_id: uuid.UUID | None = None
) -> list[MemberInfo]:
    query = (
        select(TenantMember, User, Role)
        .join(User, User.id == TenantMember.user_id)
        .join(Role, Role.id == TenantMember.role_id)
        .where(TenantMember.tenant_id == tenant_id)
        .order_by(TenantMember.status, User.email)
    )
    if member_id is not None:
        query = query.where(TenantMember.id == member_id)
    members = [MemberInfo(member=m, user=u, role=r) for m, u, r in (await session.execute(query))]
    if not members:
        return members

    by_id = {info.member.id: info for info in members}
    overrides = await session.execute(
        select(MemberEnvironmentRole.member_id, Environment.id, Environment.name, Role)
        .join(Environment, Environment.id == MemberEnvironmentRole.environment_id)
        .join(Role, Role.id == MemberEnvironmentRole.role_id)
        .where(MemberEnvironmentRole.member_id.in_(by_id))
        .order_by(Environment.name)
    )
    for mid, env_id, env_name, role in overrides.all():
        by_id[mid].environment_roles.append(
            EnvRole(environment_id=env_id, environment_name=env_name, role=role)
        )
    return members


async def get_member(
    session: AsyncSession, tenant_id: uuid.UUID, member_id: uuid.UUID
) -> MemberInfo:
    found = await list_members(session, tenant_id, member_id)
    if not found:
        raise MemberNotFoundError
    return found[0]


def _check_can_manage(actor_perms: frozenset[str], target_perms: frozenset[str]) -> None:
    if not target_perms <= actor_perms:
        raise EscalationError


async def _ensure_another_owner(
    session: AsyncSession, tenant_id: uuid.UUID, member_id: uuid.UUID
) -> None:
    # Lock the owner rows so two admins cannot demote the last two owners at the same time.
    others = (
        await session.scalars(
            select(TenantMember.id)
            .where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.role_id == OWNER_ROLE_ID,
                TenantMember.status == MemberStatus.ACTIVE,
                TenantMember.id != member_id,
            )
            .with_for_update()
        )
    ).all()
    if not others:
        raise LastOwnerError


async def update_member(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_permissions: frozenset[str],
    role_id: uuid.UUID | None,
    status: str | None,
) -> tuple[MemberInfo, dict[str, Any]]:
    """Change role and/or status. Returns the member and what changed (for the audit log)."""
    info = await get_member(session, tenant_id, member_id)
    member = info.member
    current = await get_role(session, tenant_id, member.role_id)
    _check_can_manage(actor_permissions, current.permissions)

    changes: dict[str, Any] = {}
    is_active_owner = member.role_id == OWNER_ROLE_ID and member.status == MemberStatus.ACTIVE

    if role_id is not None and role_id != member.role_id:
        new = await get_role(session, tenant_id, role_id)
        _check_can_manage(actor_permissions, new.permissions)
        if is_active_owner:
            await _ensure_another_owner(session, tenant_id, member.id)
        changes["role"] = {"from": current.role.key, "to": new.role.key}
        member.role_id = new.role.id

    if status is not None and status != member.status:
        if status == MemberStatus.SUSPENDED:
            if member.user_id == actor_user_id:
                raise SelfSuspendError
            if is_active_owner and "role" not in changes:
                await _ensure_another_owner(session, tenant_id, member.id)
        changes["status"] = {"from": member.status, "to": status}
        member.status = status

    if changes:
        await session.flush()
        info = await get_member(session, tenant_id, member_id)
    return info, changes


async def set_environment_role(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    environment_id: uuid.UUID,
    role_id: uuid.UUID,
    actor_permissions: frozenset[str],
) -> tuple[str, str | None, str]:
    """Give a member a different role inside one environment.

    Returns (environment name, previous override role key or None, new role key).
    """
    info = await get_member(session, tenant_id, member_id)
    current = await get_role(session, tenant_id, info.member.role_id)
    _check_can_manage(actor_permissions, current.permissions)

    env = await session.scalar(
        select(Environment).where(
            Environment.id == environment_id, Environment.tenant_id == tenant_id
        )
    )
    if env is None:
        raise EnvironmentNotFoundError
    new = await get_role(session, tenant_id, role_id)
    _check_can_manage(actor_permissions, new.permissions)

    previous = next(
        (er.role.key for er in info.environment_roles if er.environment_id == environment_id),
        None,
    )
    await session.execute(
        insert(MemberEnvironmentRole)
        .values(member_id=member_id, environment_id=environment_id, role_id=role_id)
        .on_conflict_do_update(
            index_elements=["member_id", "environment_id"], set_={"role_id": role_id}
        )
    )
    return env.name, previous, new.role.key


async def remove_environment_role(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    member_id: uuid.UUID,
    environment_id: uuid.UUID,
    actor_permissions: frozenset[str],
) -> str:
    """Remove an override (the member's company-wide role applies again). Returns the old key."""
    info = await get_member(session, tenant_id, member_id)
    current = await get_role(session, tenant_id, info.member.role_id)
    _check_can_manage(actor_permissions, current.permissions)

    existing = next(
        (er for er in info.environment_roles if er.environment_id == environment_id), None
    )
    if existing is None:
        raise EnvironmentNotFoundError
    _check_can_manage(
        actor_permissions, (await get_role(session, tenant_id, existing.role.id)).permissions
    )
    await session.execute(
        delete(MemberEnvironmentRole).where(
            MemberEnvironmentRole.member_id == member_id,
            MemberEnvironmentRole.environment_id == environment_id,
        )
    )
    return existing.role.key
