"""Environments API: list, create, rename, production protection, delete rules."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Environment, MemberEnvironmentRole, Tenant, User
from app.models.enums import DbEngine
from app.rbac.catalog import SystemRole
from tests.factories import (
    make_datasource,
    make_env,
    make_member,
    make_tenant,
    make_user,
    override_role,
)

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


async def company(db: AsyncSession, role: SystemRole = R.OWNER) -> tuple[Tenant, User]:
    t = await make_tenant(db)
    u = await make_user(db)
    await make_member(db, t, u, role)
    return t, u


def url(t: Tenant, env_id: uuid.UUID | None = None) -> str:
    base = f"/v1/tenants/{t.id}/environments"
    return f"{base}/{env_id}" if env_id else base


async def actions(db: AsyncSession, t: Tenant) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == t.id)))


# ---- read ----------------------------------------------------------------------------------


async def test_list_shows_counts_production_first(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db, R.VIEWER)
    dev = await make_env(db, t, "development")
    prod = await make_env(db, t, "production", prod=True)
    await make_datasource(db, t, prod, created_by=u, engine=DbEngine.POSTGRES)
    await make_datasource(db, t, prod, created_by=u, engine=DbEngine.MYSQL)
    other = await make_tenant(db)
    await make_env(db, other, "secret-env")

    r = await api.get(url(t), headers=hdr(u))
    assert r.status_code == 200
    assert [(e["name"], e["is_production"], e["datasource_count"]) for e in r.json()] == [
        ("production", True, 2),
        ("development", False, 0),
    ]
    one = await api.get(url(t, dev.id), headers=hdr(u))
    assert one.status_code == 200 and one.json()["name"] == "development"


async def test_other_companys_environment_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    foreign = await make_env(db, await make_tenant(db), "production", prod=True)
    assert (await api.get(url(t, foreign.id), headers=hdr(u))).status_code == 404
    r = await api.patch(url(t, foreign.id), json={"name": "hacked"}, headers=hdr(u))
    assert r.status_code == 404
    assert (await api.delete(url(t, foreign.id), headers=hdr(u))).status_code == 404


# ---- create ---------------------------------------------------------------------------------


async def test_dba_creates_environment(api: AsyncClient, db: AsyncSession) -> None:
    t, dba = await company(db, R.DBA)
    r = await api.post(
        url(t), json={"name": " Staging-EU ", "is_production": False}, headers=hdr(dba)
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "staging-eu"
    assert r.json()["datasource_count"] == 0
    assert await actions(db, t) == ["environment.created"]


async def test_viewer_cannot_create(api: AsyncClient, db: AsyncSession) -> None:
    t, v = await company(db, R.VIEWER)
    assert (await api.post(url(t), json={"name": "qa"}, headers=hdr(v))).status_code == 403


async def test_duplicate_name_is_409(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    await make_env(db, t, "qa")
    r = await api.post(url(t), json={"name": "QA"}, headers=hdr(u))
    assert r.status_code == 409


async def test_same_name_in_two_companies_is_fine(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    await make_env(db, await make_tenant(db), "qa")
    assert (await api.post(url(t), json={"name": "qa"}, headers=hdr(u))).status_code == 201


async def test_bad_names_are_422(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    for name in ("", "has space", "-starts-with-dash", "x" * 61, "prod!"):
        r = await api.post(url(t), json={"name": name}, headers=hdr(u))
        assert r.status_code == 422, name


# ---- update ---------------------------------------------------------------------------------


async def test_rename_and_mark_production(api: AsyncClient, db: AsyncSession) -> None:
    t, dba = await company(db, R.DBA)
    env = await make_env(db, t, "stage")
    r = await api.patch(
        url(t, env.id), json={"name": "staging", "is_production": True}, headers=hdr(dba)
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "staging" and r.json()["is_production"] is True
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "environment.updated"))
    assert row is not None
    assert row.details == {
        "name": {"from": "stage", "to": "staging"},
        "is_production": {"from": False, "to": True},
    }


async def test_rename_to_existing_name_is_409(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    await make_env(db, t, "staging")
    env = await make_env(db, t, "qa")
    r = await api.patch(url(t, env.id), json={"name": "staging"}, headers=hdr(u))
    assert r.status_code == 409


async def test_only_owner_can_unprotect_production(api: AsyncClient, db: AsyncSession) -> None:
    t, dba = await company(db, R.DBA)
    owner = await make_user(db)
    await make_member(db, t, owner, R.OWNER)
    prod = await make_env(db, t, "production", prod=True)

    r = await api.patch(url(t, prod.id), json={"is_production": False}, headers=hdr(dba))
    assert r.status_code == 403
    # A DBA may still rename it.
    r = await api.patch(url(t, prod.id), json={"name": "prod"}, headers=hdr(dba))
    assert r.status_code == 200
    r = await api.patch(url(t, prod.id), json={"is_production": False}, headers=hdr(owner))
    assert r.status_code == 200 and r.json()["is_production"] is False


async def test_no_change_writes_no_audit(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    env = await make_env(db, t, "qa")
    r = await api.patch(url(t, env.id), json={"name": "qa"}, headers=hdr(u))
    assert r.status_code == 200
    assert await actions(db, t) == []


async def test_empty_patch_is_422(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    env = await make_env(db, t, "qa")
    assert (await api.patch(url(t, env.id), json={}, headers=hdr(u))).status_code == 422


# ---- delete ---------------------------------------------------------------------------------


async def test_delete_empty_environment_removes_overrides(
    api: AsyncClient, db: AsyncSession
) -> None:
    t, owner = await company(db)
    env = await make_env(db, t, "qa")
    dev = await make_user(db)
    dev_m = await make_member(db, t, dev, R.BACKEND_DEV)
    await override_role(db, dev_m, env, R.VIEWER)

    r = await api.delete(url(t, env.id), headers=hdr(owner))
    assert r.status_code == 204
    assert await db.get(Environment, env.id) is None
    left = await db.scalar(
        select(MemberEnvironmentRole).where(MemberEnvironmentRole.member_id == dev_m.id)
    )
    assert left is None
    assert await actions(db, t) == ["environment.deleted"]


async def test_cannot_delete_environment_with_databases(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    env = await make_env(db, t, "qa")
    await make_datasource(db, t, env, created_by=owner)
    r = await api.delete(url(t, env.id), headers=hdr(owner))
    assert r.status_code == 409
    assert "1 database" in r.json()["error"]["message"]


async def test_only_owner_can_delete_production(api: AsyncClient, db: AsyncSession) -> None:
    t, dba = await company(db, R.DBA)
    prod = await make_env(db, t, "production", prod=True)
    qa = await make_env(db, t, "qa")
    assert (await api.delete(url(t, prod.id), headers=hdr(dba))).status_code == 403
    assert (await api.delete(url(t, qa.id), headers=hdr(dba))).status_code == 204
