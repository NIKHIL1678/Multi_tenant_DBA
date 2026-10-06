"""Permission resolution.

Rules:
1. The user, the tenant and the membership must all be active; otherwise no permissions.
2. If an environment is given and the member has an override for it, that role is used;
   otherwise the member's tenant-wide role.
3. The effective role must be a system role or belong to the same tenant. A role from
   another tenant grants nothing, even if a bad row points at it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Datasource,
    MemberEnvironmentRole,
    Role,
    RolePermission,
    Tenant,
    TenantMember,
    User,
)
from app.models.enums import MemberStatus, TenantStatus, UserStatus
from app.rbac.catalog import Permission


@dataclass(frozen=True, slots=True)
class AccessContext:
    tenant_id: uuid.UUID
    member_id: uuid.UUID
    role_id: uuid.UUID
    role_key: str
    environment_id: uuid.UUID | None
    permissions: frozenset[str]

    def has(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions


async def resolve_access(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    environment_id: uuid.UUID | None = None,
) -> AccessContext | None:
    """Return the caller's effective access in a tenant (optionally one environment)."""
    member_row = (
        await session.execute(
            select(TenantMember.id, TenantMember.role_id)
            .join(User, User.id == TenantMember.user_id)
            .join(Tenant, Tenant.id == TenantMember.tenant_id)
            .where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
                TenantMember.status == MemberStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )
    ).one_or_none()
    if member_row is None:
        return None

    member_id, role_id = member_row.id, member_row.role_id

    if environment_id is not None:
        override = await session.scalar(
            select(MemberEnvironmentRole.role_id).where(
                MemberEnvironmentRole.member_id == member_id,
                MemberEnvironmentRole.environment_id == environment_id,
            )
        )
        if override is not None:
            role_id = override

    role_key = await session.scalar(
        select(Role.key).where(
            Role.id == role_id,
            or_(Role.tenant_id.is_(None), Role.tenant_id == tenant_id),
        )
    )
    if role_key is None:
        return None

    perms = (
        await session.scalars(
            select(RolePermission.permission_key).where(RolePermission.role_id == role_id)
        )
    ).all()

    return AccessContext(
        tenant_id=tenant_id,
        member_id=member_id,
        role_id=role_id,
        role_key=role_key,
        environment_id=environment_id,
        permissions=frozenset(perms),
    )


async def resolve_datasource_access(
    session: AsyncSession, *, user_id: uuid.UUID, datasource_id: uuid.UUID
) -> AccessContext | None:
    """Access for a specific datasource: scoped to its tenant and environment."""
    ds = (
        await session.execute(
            select(Datasource.tenant_id, Datasource.environment_id).where(
                Datasource.id == datasource_id
            )
        )
    ).one_or_none()
    if ds is None:
        return None
    return await resolve_access(
        session, user_id=user_id, tenant_id=ds.tenant_id, environment_id=ds.environment_id
    )


async def has_permission(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permission: Permission,
    environment_id: uuid.UUID | None = None,
) -> bool:
    ctx = await resolve_access(
        session, user_id=user_id, tenant_id=tenant_id, environment_id=environment_id
    )
    return ctx is not None and ctx.has(permission)
