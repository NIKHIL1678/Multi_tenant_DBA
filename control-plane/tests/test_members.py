"""Members and roles API: listing, role changes, suspension, environment overrides, safety rules."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Tenant, TenantMember, User
from app.models.enums import MemberStatus
from app.rbac.catalog import Permission, SystemRole, system_role_id
from app.rbac.service import resolve_access
from tests.factories import (
    make_custom_role,
    make_env,
    make_member,
    make_tenant,
    make_user,
    override_role,
)

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def rid(role: SystemRole) -> str:
    return str(system_role_id(role))


async def company(db: AsyncSession) -> tuple[Tenant, User, TenantMember]:
    """A company with one Owner."""
    t = await make_tenant(db)
    owner = await make_user(db)
    m = await make_member(db, t, owner, R.OWNER)
    return t, owner, m


async def add(
    db: AsyncSession, t: Tenant, role: SystemRole, **kw: object
) -> tuple[User, TenantMember]:
    u = await make_user(db)
    return u, await make_member(db, t, u, role, **kw)


async def actions(db: AsyncSession, t: Tenant) -> list[str]:
    rows = await db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == t.id))
    return list(rows)


# ---- read ----------------------------------------------------------------------------------


async def test_roles_lists_system_and_own_custom_roles(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    other = await make_tenant(db)
    await make_custom_role(db, t, "auditor", {Permission.AUDIT_READ})
    await make_custom_role(db, other, "secret", {Permission.DATA_READ})

    r = await api.get(f"/v1/tenants/{t.id}/roles", headers=hdr(owner))
    assert r.status_code == 200
    keys = [x["key"] for x in r.json()]
    assert set(keys) == {"owner", "dba", "it_admin", "backend_dev", "viewer", "auditor"}
    viewer = next(x for x in r.json() if x["key"] == "viewer")
    assert viewer["permissions"] == ["findings.read", "metadata.read"]


async def test_members_list_includes_overrides(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    dev, dev_m = await add(db, t, R.BACKEND_DEV)
    prod = await make_env(db, t, "production", prod=True)
    await override_role(db, dev_m, prod, R.VIEWER)
    viewer, _ = await add(db, t, R.VIEWER)

    r = await api.get(f"/v1/tenants/{t.id}/members", headers=hdr(viewer))
    assert r.status_code == 200
    by_email = {m["email"]: m for m in r.json()}
    assert set(by_email) == {owner.email, dev.email, viewer.email}
    d = by_email[dev.email]
    assert d["role"]["key"] == "backend_dev"
    assert d["environment_roles"] == [
        {
            "environment_id": str(prod.id),
            "environment_name": "production",
            "role": {"id": rid(R.VIEWER), "key": "viewer", "name": "Viewer"},
        }
    ]


async def test_member_of_other_company_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    _, _, other_owner_m = await company(db)
    r = await api.get(f"/v1/tenants/{t.id}/members/{other_owner_m.id}", headers=hdr(owner))
    assert r.status_code == 404
    # And outsiders cannot list our members at all.
    outsider = await make_user(db)
    r = await api.get(f"/v1/tenants/{t.id}/members", headers=hdr(outsider))
    assert r.status_code == 404


# ---- role changes ----------------------------------------------------------------------------


async def test_owner_changes_role_and_it_is_audited(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    u, m = await add(db, t, R.VIEWER)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{m.id}", json={"role_id": rid(R.DBA)}, headers=hdr(owner)
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"]["key"] == "dba"

    access = await resolve_access(db, user_id=u.id, tenant_id=t.id)
    assert access is not None and access.has(Permission.ACTIONS_EXECUTE)

    row = await db.scalar(select(AuditLog).where(AuditLog.action == "member.role_changed"))
    assert row is not None and row.tenant_id == t.id
    assert row.details == {"email": u.email, "from": "viewer", "to": "dba"}


async def test_member_without_members_manage_gets_403(api: AsyncClient, db: AsyncSession) -> None:
    t, _, _ = await company(db)
    dba, _ = await add(db, t, R.DBA)
    _, m = await add(db, t, R.VIEWER)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{m.id}", json={"status": "suspended"}, headers=hdr(dba)
    )
    assert r.status_code == 403


async def test_it_admin_cannot_grant_more_than_they_have(
    api: AsyncClient, db: AsyncSession
) -> None:
    t, _, _ = await company(db)
    it, _ = await add(db, t, R.IT_ADMIN)
    _, m = await add(db, t, R.VIEWER)
    url = f"/v1/tenants/{t.id}/members/{m.id}"

    # DBA has data.read / actions.*, which an IT Admin does not have.
    r = await api.patch(url, json={"role_id": rid(R.DBA)}, headers=hdr(it))
    assert r.status_code == 403
    r = await api.patch(url, json={"role_id": rid(R.OWNER)}, headers=hdr(it))
    assert r.status_code == 403
    # But Viewer -> IT Admin is fine (same access as their own).
    r = await api.patch(url, json={"role_id": rid(R.IT_ADMIN)}, headers=hdr(it))
    assert r.status_code == 200


async def test_it_admin_cannot_touch_owner_or_dba(api: AsyncClient, db: AsyncSession) -> None:
    t, _, owner_m = await company(db)
    it, _ = await add(db, t, R.IT_ADMIN)
    _, dba_m = await add(db, t, R.DBA)
    for target in (owner_m, dba_m):
        r = await api.patch(
            f"/v1/tenants/{t.id}/members/{target.id}",
            json={"status": "suspended"},
            headers=hdr(it),
        )
        assert r.status_code == 403


async def test_role_from_another_company_is_rejected(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    other = await make_tenant(db)
    foreign = await make_custom_role(db, other, "foreign", {Permission.METADATA_READ})
    _, m = await add(db, t, R.VIEWER)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{m.id}", json={"role_id": str(foreign.id)}, headers=hdr(owner)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_role"


async def test_empty_patch_is_422(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, owner_m = await company(db)
    r = await api.patch(f"/v1/tenants/{t.id}/members/{owner_m.id}", json={}, headers=hdr(owner))
    assert r.status_code == 422


# ---- owners and suspension -------------------------------------------------------------------


async def test_last_owner_cannot_be_demoted(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, owner_m = await company(db)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{owner_m.id}",
        json={"role_id": rid(R.VIEWER)},
        headers=hdr(owner),
    )
    assert r.status_code == 409
    assert "Owner" in r.json()["error"]["message"]


async def test_owner_can_step_down_when_another_owner_exists(
    api: AsyncClient, db: AsyncSession
) -> None:
    t, owner, owner_m = await company(db)
    await add(db, t, R.OWNER)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{owner_m.id}",
        json={"role_id": rid(R.DBA)},
        headers=hdr(owner),
    )
    assert r.status_code == 200
    assert r.json()["role"]["key"] == "dba"


async def test_suspended_owner_does_not_count(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, owner_m = await company(db)
    await add(db, t, R.OWNER, status=MemberStatus.SUSPENDED)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{owner_m.id}",
        json={"role_id": rid(R.VIEWER)},
        headers=hdr(owner),
    )
    assert r.status_code == 409


async def test_cannot_suspend_yourself(api: AsyncClient, db: AsyncSession) -> None:
    t, _, _ = await company(db)
    it, it_m = await add(db, t, R.IT_ADMIN)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{it_m.id}", json={"status": "suspended"}, headers=hdr(it)
    )
    assert r.status_code == 409


async def test_suspend_then_reactivate(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    u, m = await add(db, t, R.DBA)
    url = f"/v1/tenants/{t.id}/members/{m.id}"

    r = await api.patch(url, json={"status": "suspended"}, headers=hdr(owner))
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert await resolve_access(db, user_id=u.id, tenant_id=t.id) is None
    # The suspended person is locked out immediately.
    assert (await api.get(f"/v1/tenants/{t.id}", headers=hdr(u))).status_code == 404

    r = await api.patch(url, json={"status": "active"}, headers=hdr(owner))
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert await actions(db, t) == ["member.suspended", "member.reactivated"]


# ---- environment overrides ---------------------------------------------------------------------


async def test_set_change_and_remove_environment_role(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    u, m = await add(db, t, R.BACKEND_DEV)
    prod = await make_env(db, t, "production", prod=True)
    url = f"/v1/tenants/{t.id}/members/{m.id}/environments/{prod.id}"

    r = await api.put(url, json={"role_id": rid(R.VIEWER)}, headers=hdr(owner))
    assert r.status_code == 200, r.text
    assert r.json()["environment_roles"][0]["role"]["key"] == "viewer"
    in_prod = await resolve_access(db, user_id=u.id, tenant_id=t.id, environment_id=prod.id)
    assert in_prod is not None and not in_prod.has(Permission.DATA_READ)

    # PUT again replaces (no duplicate row).
    r = await api.put(url, json={"role_id": rid(R.DBA)}, headers=hdr(owner))
    assert [er["role"]["key"] for er in r.json()["environment_roles"]] == ["dba"]

    r = await api.delete(url, headers=hdr(owner))
    assert r.status_code == 204
    in_prod = await resolve_access(db, user_id=u.id, tenant_id=t.id, environment_id=prod.id)
    assert in_prod is not None and in_prod.role_key == "backend_dev"

    assert await actions(db, t) == [
        "member.environment_role_set",
        "member.environment_role_set",
        "member.environment_role_removed",
    ]


async def test_environment_of_other_company_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    _, m = await add(db, t, R.VIEWER)
    other = await make_tenant(db)
    foreign_env = await make_env(db, other, "production", prod=True)
    r = await api.put(
        f"/v1/tenants/{t.id}/members/{m.id}/environments/{foreign_env.id}",
        json={"role_id": rid(R.VIEWER)},
        headers=hdr(owner),
    )
    assert r.status_code == 404


async def test_remove_missing_override_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    _, m = await add(db, t, R.VIEWER)
    env = await make_env(db, t, "staging")
    r = await api.delete(
        f"/v1/tenants/{t.id}/members/{m.id}/environments/{env.id}", headers=hdr(owner)
    )
    assert r.status_code == 404


async def test_it_admin_cannot_set_dba_override(api: AsyncClient, db: AsyncSession) -> None:
    t, _, _ = await company(db)
    it, _ = await add(db, t, R.IT_ADMIN)
    _, m = await add(db, t, R.VIEWER)
    env = await make_env(db, t, "staging")
    r = await api.put(
        f"/v1/tenants/{t.id}/members/{m.id}/environments/{env.id}",
        json={"role_id": rid(R.DBA)},
        headers=hdr(it),
    )
    assert r.status_code == 403


async def test_unknown_member_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, owner, _ = await company(db)
    r = await api.patch(
        f"/v1/tenants/{t.id}/members/{uuid.uuid4()}", json={"status": "active"}, headers=hdr(owner)
    )
    assert r.status_code == 404
