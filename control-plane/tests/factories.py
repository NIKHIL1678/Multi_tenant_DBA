"""Helpers that create test rows with sensible defaults."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Connector,
    Datasource,
    Environment,
    MemberEnvironmentRole,
    Role,
    RolePermission,
    Tenant,
    TenantMember,
    User,
)
from app.models.enums import AuthProvider, DbEngine
from app.rbac.catalog import Permission, SystemRole, system_role_id


async def make_tenant(db: AsyncSession, **kw: object) -> Tenant:
    tid = uuid.uuid4()
    t = Tenant(id=tid, name=f"Tenant {tid.hex[:8]}", slug=f"t-{tid.hex[:12]}", **kw)
    db.add(t)
    await db.flush()
    return t


async def make_user(db: AsyncSession, **kw: object) -> User:
    uid = uuid.uuid4()
    fields: dict[str, object] = {
        "id": uid,
        "email": f"{uid.hex[:12]}@example.test",
        "auth_provider": AuthProvider.ZIPZY_ACCOUNTS,
        "external_id": str(uid),
    }
    fields.update(kw)
    u = User(**fields)
    db.add(u)
    await db.flush()
    return u


async def make_member(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    role: SystemRole | uuid.UUID = SystemRole.VIEWER,
    **kw: object,
) -> TenantMember:
    role_id = system_role_id(role) if isinstance(role, SystemRole) else role
    m = TenantMember(tenant_id=tenant.id, user_id=user.id, role_id=role_id, **kw)
    db.add(m)
    await db.flush()
    return m


async def make_env(db: AsyncSession, tenant: Tenant, name: str, prod: bool = False) -> Environment:
    e = Environment(tenant_id=tenant.id, name=name, is_production=prod)
    db.add(e)
    await db.flush()
    return e


async def override_role(
    db: AsyncSession, member: TenantMember, env: Environment, role: SystemRole | uuid.UUID
) -> None:
    role_id = system_role_id(role) if isinstance(role, SystemRole) else role
    db.add(MemberEnvironmentRole(member_id=member.id, environment_id=env.id, role_id=role_id))
    await db.flush()


async def make_custom_role(
    db: AsyncSession, tenant: Tenant, key: str, perms: set[Permission]
) -> Role:
    r = Role(tenant_id=tenant.id, key=key, name=key.title(), is_system=False)
    db.add(r)
    await db.flush()
    db.add_all([RolePermission(role_id=r.id, permission_key=str(p)) for p in perms])
    await db.flush()
    return r


async def make_datasource(
    db: AsyncSession, tenant: Tenant, env: Environment, created_by: User
) -> Datasource:
    c = Connector(
        tenant_id=tenant.id, name=f"conn-{uuid.uuid4().hex[:8]}", created_by=created_by.id
    )
    db.add(c)
    await db.flush()
    ds = Datasource(
        tenant_id=tenant.id,
        connector_id=c.id,
        environment_id=env.id,
        local_name="main-mysql",
        engine=DbEngine.MYSQL,
    )
    db.add(ds)
    await db.flush()
    return ds