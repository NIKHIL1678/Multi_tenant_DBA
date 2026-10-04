import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MemberStatus, TenantStatus, UserStatus
from app.rbac.catalog import SYSTEM_ROLE_PERMISSIONS, Permission, SystemRole
from app.rbac.service import has_permission, resolve_access, resolve_datasource_access
from tests.factories import (
    make_custom_role,
    make_datasource,
    make_env,
    make_member,
    make_tenant,
    make_user,
    override_role,
)

P = Permission


@pytest.mark.parametrize("role", list(SystemRole))
async def test_system_role_grants_exact_permissions(db: AsyncSession, role: SystemRole) -> None:
    t, u = await make_tenant(db), await make_user(db)
    await make_member(db, t, u, role)
    ctx = await resolve_access(db, user_id=u.id, tenant_id=t.id)
    assert ctx is not None
    assert ctx.role_key == role.value
    assert ctx.permissions == {str(p) for p in SYSTEM_ROLE_PERMISSIONS[role]}


async def test_it_admin_cannot_read_row_data(db: AsyncSession) -> None:
    t, u = await make_tenant(db), await make_user(db)
    await make_member(db, t, u, SystemRole.IT_ADMIN)
    assert await has_permission(db, user_id=u.id, tenant_id=t.id, permission=P.METADATA_READ)
    assert not await has_permission(db, user_id=u.id, tenant_id=t.id, permission=P.DATA_READ)


async def test_backend_dev_can_request_but_not_execute(db: AsyncSession) -> None:
    t, u = await make_tenant(db), await make_user(db)
    await make_member(db, t, u, SystemRole.BACKEND_DEV)
    assert await has_permission(db, user_id=u.id, tenant_id=t.id, permission=P.ACTIONS_REQUEST)
    assert not await has_permission(db, user_id=u.id, tenant_id=t.id, permission=P.ACTIONS_EXECUTE)


async def test_environment_override_restricts_production(db: AsyncSession) -> None:
    t, u = await make_tenant(db), await make_user(db)
    prod = await make_env(db, t, "production", prod=True)
    staging = await make_env(db, t, "staging")
    m = await make_member(db, t, u, SystemRole.BACKEND_DEV)
    await override_role(db, m, prod, SystemRole.VIEWER)

    prod_ctx = await resolve_access(db, user_id=u.id, tenant_id=t.id, environment_id=prod.id)
    stg_ctx = await resolve_access(db, user_id=u.id, tenant_id=t.id, environment_id=staging.id)
    assert prod_ctx is not None and stg_ctx is not None
    assert not prod_ctx.has(P.DATA_READ)
    assert stg_ctx.has(P.DATA_READ)


async def test_datasource_access_uses_its_environment(db: AsyncSession) -> None:
    t, u = await make_tenant(db), await make_user(db)
    prod = await make_env(db, t, "production", prod=True)
    m = await make_member(db, t, u, SystemRole.BACKEND_DEV)
    await override_role(db, m, prod, SystemRole.VIEWER)
    ds = await make_datasource(db, t, prod, created_by=u)

    ctx = await resolve_datasource_access(db, user_id=u.id, datasource_id=ds.id)
    assert ctx is not None
    assert ctx.environment_id == prod.id
    assert ctx.role_key == SystemRole.VIEWER.value
    assert not ctx.has(P.DATA_READ)


async def test_unknown_datasource_grants_nothing(db: AsyncSession) -> None:
    u = await make_user(db)
    assert await resolve_datasource_access(db, user_id=u.id, datasource_id=uuid.uuid4()) is None


async def test_non_member_gets_nothing(db: AsyncSession) -> None:
    t_a, t_b, u = await make_tenant(db), await make_tenant(db), await make_user(db)
    await make_member(db, t_a, u, SystemRole.OWNER)
    assert await resolve_access(db, user_id=u.id, tenant_id=t_b.id) is None


async def test_user_in_multiple_tenants_has_independent_roles(db: AsyncSession) -> None:
    t_a, t_b, u = await make_tenant(db), await make_tenant(db), await make_user(db)
    await make_member(db, t_a, u, SystemRole.DBA)
    await make_member(db, t_b, u, SystemRole.VIEWER)
    a = await resolve_access(db, user_id=u.id, tenant_id=t_a.id)
    b = await resolve_access(db, user_id=u.id, tenant_id=t_b.id)
    assert a is not None and a.has(P.ACTIONS_EXECUTE)
    assert b is not None and not b.has(P.ACTIONS_EXECUTE)


@pytest.mark.parametrize("what", ["member", "user", "tenant"])
async def test_inactive_anything_revokes_access(db: AsyncSession, what: str) -> None:
    t = await make_tenant(db, **({"status": TenantStatus.SUSPENDED} if what == "tenant" else {}))
    u = await make_user(db, **({"status": UserStatus.DISABLED} if what == "user" else {}))
    await make_member(
        db,
        t,
        u,
        SystemRole.OWNER,
        **({"status": MemberStatus.SUSPENDED} if what == "member" else {}),
    )
    assert await resolve_access(db, user_id=u.id, tenant_id=t.id) is None


async def test_custom_tenant_role(db: AsyncSession) -> None:
    t, u = await make_tenant(db), await make_user(db)
    auditor = await make_custom_role(db, t, "auditor", {P.AUDIT_READ, P.METADATA_READ})
    await make_member(db, t, u, auditor.id)
    ctx = await resolve_access(db, user_id=u.id, tenant_id=t.id)
    assert ctx is not None
    assert ctx.permissions == {str(P.AUDIT_READ), str(P.METADATA_READ)}


async def test_role_from_another_tenant_grants_nothing(db: AsyncSession) -> None:
    t_a, t_b, u = await make_tenant(db), await make_tenant(db), await make_user(db)
    foreign = await make_custom_role(db, t_b, "superuser", set(Permission))
    await make_member(db, t_a, u, foreign.id)
    assert await resolve_access(db, user_id=u.id, tenant_id=t_a.id) is None