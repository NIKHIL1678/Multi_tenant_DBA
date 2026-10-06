"""Company (tenant) API: creation, the permission guard, the block wall, audit."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Environment, TenantMember
from app.models.enums import DbEngine, MemberStatus
from app.rbac.catalog import SystemRole, system_role_id
from app.services.tenants import slugify
from tests.factories import make_datasource, make_env, make_member, make_tenant, make_user


def hdr(email: str) -> dict[str, str]:
    return {"X-Dev-User": email}


# ---- create -------------------------------------------------------------------------------


async def test_create_makes_owner_envs_and_audit(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    r = await api.post("/v1/tenants", json={"name": "  Kapoor   Steel "}, headers=hdr(u.email))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Kapoor Steel"
    assert body["slug"] == "kapoor-steel"
    assert body["my_role_key"] == "owner"
    assert "org.manage" in body["my_permissions"]
    tid = uuid.UUID(body["id"])

    member = await db.scalar(select(TenantMember).where(TenantMember.tenant_id == tid))
    assert member is not None
    assert member.user_id == u.id
    assert member.role_id == system_role_id(SystemRole.OWNER)

    envs = {
        e.name: e.is_production
        for e in await db.scalars(select(Environment).where(Environment.tenant_id == tid))
    }
    assert envs == {"production": True, "staging": False, "development": False}

    audit = (await db.scalars(select(AuditLog).where(AuditLog.tenant_id == tid))).all()
    assert [a.action for a in audit] == ["tenant.created"]
    assert audit[0].actor_id == u.id
    assert audit[0].request_id == r.headers["X-Request-ID"]


async def test_create_requires_sign_in(api: AsyncClient) -> None:
    r = await api.post("/v1/tenants", json={"name": "X Corp"})
    assert r.status_code == 401


async def test_auto_slug_gets_suffix_when_taken(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    await make_tenant(db, slug="mehta-traders")
    r = await api.post("/v1/tenants", json={"name": "Mehta Traders"}, headers=hdr(u.email))
    assert r.status_code == 201
    assert r.json()["slug"].startswith("mehta-traders-")


async def test_explicit_slug_conflict_is_409(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    await make_tenant(db, slug="taken-name")
    r = await api.post(
        "/v1/tenants", json={"name": "Whatever", "slug": "Taken-Name"}, headers=hdr(u.email)
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_bad_or_reserved_slug_is_422(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    for slug in ("a", "-bad-", "has space", "double--hyphen", "admin"):
        r = await api.post("/v1/tenants", json={"name": "X", "slug": slug}, headers=hdr(u.email))
        assert r.status_code == 422, slug
        assert r.json()["error"]["code"] == "validation_error"


def test_slugify() -> None:
    assert slugify("Sharma Textiles Pvt. Ltd.") == "sharma-textiles-pvt-ltd"
    assert slugify("AB") == "company-ab"
    assert slugify("!!!") == "company"
    assert len(slugify("x" * 200)) <= 40


# ---- list / get ---------------------------------------------------------------------------


async def test_list_shows_only_my_active_memberships(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    mine, suspended, other = await make_tenant(db), await make_tenant(db), await make_tenant(db)
    await make_member(db, mine, u, SystemRole.VIEWER)
    await make_member(db, suspended, u, SystemRole.OWNER, status=MemberStatus.SUSPENDED)
    await make_member(db, other, await make_user(db), SystemRole.OWNER)

    r = await api.get("/v1/tenants", headers=hdr(u.email))
    assert r.status_code == 200
    body = r.json()
    assert [t["id"] for t in body] == [str(mine.id)]
    assert body[0]["my_role_key"] == "viewer"
    assert body[0]["my_permissions"] == ["findings.read", "metadata.read"]


async def test_member_can_read_tenant(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t = await make_tenant(db)
    await make_member(db, t, u, SystemRole.VIEWER)
    r = await api.get(f"/v1/tenants/{t.id}", headers=hdr(u.email))
    assert r.status_code == 200
    assert r.json()["slug"] == t.slug


async def test_outsider_gets_404_not_403(api: AsyncClient, db: AsyncSession) -> None:
    """The block wall: another company's ID looks exactly like a missing one."""
    outsider = await make_user(db)
    t = await make_tenant(db)
    await make_member(db, t, await make_user(db), SystemRole.OWNER)

    real = await api.get(f"/v1/tenants/{t.id}", headers=hdr(outsider.email))
    fake = await api.get(f"/v1/tenants/{uuid.uuid4()}", headers=hdr(outsider.email))
    assert real.status_code == fake.status_code == 404
    assert real.json()["error"]["message"] == fake.json()["error"]["message"]

    patch = await api.patch(
        f"/v1/tenants/{t.id}", json={"name": "Hacked"}, headers=hdr(outsider.email)
    )
    assert patch.status_code == 404


async def test_suspended_member_gets_404(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t = await make_tenant(db)
    await make_member(db, t, u, SystemRole.OWNER, status=MemberStatus.SUSPENDED)
    r = await api.get(f"/v1/tenants/{t.id}", headers=hdr(u.email))
    assert r.status_code == 404


async def test_bad_tenant_id_is_422(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    r = await api.get("/v1/tenants/not-a-uuid", headers=hdr(u.email))
    assert r.status_code == 422


# ---- update -------------------------------------------------------------------------------


async def test_owner_can_rename_and_it_is_audited(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t = await make_tenant(db, name="Old Name")
    await make_member(db, t, u, SystemRole.OWNER)

    r = await api.patch(f"/v1/tenants/{t.id}", json={"name": "New Name"}, headers=hdr(u.email))
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"

    row = await db.scalar(
        select(AuditLog).where(AuditLog.tenant_id == t.id, AuditLog.action == "tenant.renamed")
    )
    assert row is not None
    assert row.details == {"from": "Old Name", "to": "New Name"}


async def test_rename_to_same_name_writes_no_audit(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t = await make_tenant(db, name="Same")
    await make_member(db, t, u, SystemRole.OWNER)
    r = await api.patch(f"/v1/tenants/{t.id}", json={"name": "Same"}, headers=hdr(u.email))
    assert r.status_code == 200
    count = (await db.scalars(select(AuditLog).where(AuditLog.tenant_id == t.id))).all()
    assert count == []


async def test_dba_cannot_rename_gets_403(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t = await make_tenant(db)
    await make_member(db, t, u, SystemRole.DBA)
    r = await api.patch(f"/v1/tenants/{t.id}", json={"name": "Nope"}, headers=hdr(u.email))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


# ---- overview -----------------------------------------------------------------------------


async def test_overview_counts_only_this_tenant(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db)
    t, other = await make_tenant(db), await make_tenant(db)
    await make_member(db, t, u, SystemRole.VIEWER)
    await make_member(db, t, await make_user(db), SystemRole.DBA)
    await make_member(db, t, await make_user(db), SystemRole.DBA, status=MemberStatus.SUSPENDED)
    prod = await make_env(db, t, "production", prod=True)
    await make_env(db, t, "staging")
    await make_datasource(db, t, prod, created_by=u, engine=DbEngine.POSTGRES)
    await make_datasource(db, t, prod, created_by=u, engine=DbEngine.POSTGRES)
    await make_datasource(db, t, prod, created_by=u, engine=DbEngine.MYSQL)
    other_env = await make_env(db, other, "production", prod=True)
    await make_datasource(db, other, other_env, created_by=u, engine=DbEngine.MONGODB)

    r = await api.get(f"/v1/tenants/{t.id}/overview", headers=hdr(u.email))
    assert r.status_code == 200
    body = r.json()
    assert body["environments"] == 2
    assert body["members"] == 2
    assert body["datasources_by_engine"] == {"postgres": 2, "mysql": 1}
    assert body["connectors_by_status"] == {"pending": 3}  # the other company's is not counted
