"""Company (tenant) business logic. Endpoints stay thin; the rules live here."""

import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Connector,
    Datasource,
    Environment,
    Role,
    RolePermission,
    Tenant,
    TenantMember,
)
from app.models.enums import MemberStatus, TenantStatus
from app.rbac.catalog import SystemRole, system_role_id
from app.schemas.tenants import RESERVED_SLUGS

# Every new company starts with these. Only "production" is marked as production.
DEFAULT_ENVIRONMENTS: tuple[tuple[str, bool], ...] = (
    ("production", True),
    ("staging", False),
    ("development", False),
)


class SlugTakenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class TenantWithRole:
    tenant: Tenant
    role_key: str
    permissions: frozenset[str]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    if len(slug) < 3:
        slug = f"company-{slug}".strip("-")
    return slug


async def _slug_free(session: AsyncSession, slug: str) -> bool:
    if slug in RESERVED_SLUGS:
        return False
    return await session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is None


async def _pick_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)
    if await _slug_free(session, base):
        return base
    for _ in range(5):
        candidate = f"{base}-{secrets.token_hex(2)}"
        if await _slug_free(session, candidate):
            return candidate
    return f"{base}-{secrets.token_hex(4)}"


async def create_tenant(
    session: AsyncSession, *, owner_id: uuid.UUID, name: str, slug: str | None
) -> Tenant:
    """Create the company, make the caller its Owner, add the default environments."""
    if slug is not None:
        if not await _slug_free(session, slug):
            raise SlugTakenError
    else:
        slug = await _pick_slug(session, name)

    tenant = Tenant(name=name, slug=slug)
    try:
        async with session.begin_nested():  # a concurrent request can still take the slug
            session.add(tenant)
            await session.flush()
    except IntegrityError as exc:
        raise SlugTakenError from exc

    session.add(
        TenantMember(
            tenant_id=tenant.id, user_id=owner_id, role_id=system_role_id(SystemRole.OWNER)
        )
    )
    session.add_all(
        Environment(tenant_id=tenant.id, name=env_name, is_production=is_prod)
        for env_name, is_prod in DEFAULT_ENVIRONMENTS
    )
    await session.flush()
    return tenant


async def list_my_tenants(session: AsyncSession, user_id: uuid.UUID) -> list[TenantWithRole]:
    """Companies the user is an active member of, with their tenant-wide role."""
    rows = (
        await session.execute(
            select(Tenant, Role.id, Role.key)
            .join(TenantMember, TenantMember.tenant_id == Tenant.id)
            .join(Role, Role.id == TenantMember.role_id)
            .where(
                TenantMember.user_id == user_id,
                TenantMember.status == MemberStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
            .order_by(Tenant.name)
        )
    ).all()
    role_ids = {role_id for _, role_id, _ in rows}
    perms: dict[uuid.UUID, set[str]] = {rid: set() for rid in role_ids}
    if role_ids:
        for rid, key in (
            await session.execute(
                select(RolePermission.role_id, RolePermission.permission_key).where(
                    RolePermission.role_id.in_(role_ids)
                )
            )
        ).all():
            perms[rid].add(key)
    return [
        TenantWithRole(tenant=t, role_key=key, permissions=frozenset(perms[rid]))
        for t, rid, key in rows
    ]


async def get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:  # the permission guard already proved it exists
        raise LookupError(tenant_id)
    return tenant


async def overview_counts(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    environments = await session.scalar(
        select(func.count()).select_from(Environment).where(Environment.tenant_id == tenant_id)
    )
    members = await session.scalar(
        select(func.count())
        .select_from(TenantMember)
        .where(TenantMember.tenant_id == tenant_id, TenantMember.status == MemberStatus.ACTIVE)
    )
    connectors = (
        await session.execute(
            select(Connector.status, func.count())
            .where(Connector.tenant_id == tenant_id)
            .group_by(Connector.status)
        )
    ).all()
    datasources = (
        await session.execute(
            select(Datasource.engine, func.count())
            .where(Datasource.tenant_id == tenant_id)
            .group_by(Datasource.engine)
        )
    ).all()
    return (
        environments or 0,
        members or 0,
        {status: n for status, n in connectors},
        {engine: n for engine, n in datasources},
    )
