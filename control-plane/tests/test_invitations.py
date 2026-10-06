"""Invitations: invite, list, revoke, preview, accept, and the safety rules around them."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Invitation, Tenant, TenantMember, User
from app.models.enums import MemberStatus, TenantStatus
from app.rbac.catalog import Permission, SystemRole, system_role_id
from app.rbac.service import resolve_access
from tests.factories import make_custom_role, make_member, make_tenant, make_user

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def rid(role: SystemRole) -> str:
    return str(system_role_id(role))


async def company(db: AsyncSession) -> tuple[Tenant, User]:
    t = await make_tenant(db, name="Sharma Textiles")
    owner = await make_user(db, full_name="Anil Sharma")
    await make_member(db, t, owner, R.OWNER)
    return t, owner


async def invite(
    api: AsyncClient, t: Tenant, by: User, email: str, role: SystemRole = R.VIEWER
) -> str:
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": email, "role_id": rid(role)},
        headers=hdr(by),
    )
    assert r.status_code == 201, r.text
    token: str = r.json()["token"]
    return token


async def actions(db: AsyncSession, t: Tenant) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == t.id)))


# ---- create / list / revoke ------------------------------------------------------------------


async def test_invite_stores_only_the_hash(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": "New.Person@Example.com", "role_id": rid(R.DBA)},
        headers=hdr(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new.person@example.com"
    assert body["role"]["key"] == "dba"
    assert body["invited_by_email"] == owner.email

    inv = await db.scalar(select(Invitation).where(Invitation.tenant_id == t.id))
    assert inv is not None
    assert body["token"] not in inv.token_hash
    assert inv.expires_at > datetime.now(UTC) + timedelta(days=6)
    assert await actions(db, t) == ["invitation.created"]


async def test_list_shows_only_pending(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    await invite(api, t, owner, "a@example.com")
    await invite(api, t, owner, "b@example.com")
    expired = Invitation(
        tenant_id=t.id,
        email="old@example.com",
        role_id=system_role_id(R.VIEWER),
        token_hash=uuid.uuid4().hex,
        invited_by=owner.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(expired)
    await db.flush()

    r = await api.get(f"/v1/tenants/{t.id}/invitations", headers=hdr(owner))
    assert r.status_code == 200
    assert {i["email"] for i in r.json()} == {"a@example.com", "b@example.com"}
    assert "token" not in r.json()[0]


async def test_reinvite_replaces_old_link(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    first = await invite(api, t, owner, "x@example.com")
    second = await invite(api, t, owner, "x@example.com", R.DBA)

    r = await api.post("/v1/invitations/preview", json={"token": first})
    assert r.status_code == 404
    r = await api.post("/v1/invitations/preview", json={"token": second})
    assert r.status_code == 200 and r.json()["role_name"] == "DBA"
    pending = (await api.get(f"/v1/tenants/{t.id}/invitations", headers=hdr(owner))).json()
    assert len(pending) == 1


async def test_cannot_invite_existing_member(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    for status in (MemberStatus.ACTIVE, MemberStatus.SUSPENDED):
        u = await make_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com")
        await make_member(db, t, u, R.VIEWER, status=status)
        r = await api.post(
            f"/v1/tenants/{t.id}/invitations",
            json={"email": u.email.upper(), "role_id": rid(R.VIEWER)},
            headers=hdr(owner),
        )
        assert r.status_code == 409


async def test_it_admin_cannot_invite_a_dba(api: AsyncClient, db: AsyncSession) -> None:
    t, _ = await company(db)
    it = await make_user(db)
    await make_member(db, t, it, R.IT_ADMIN)
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": "dba@example.com", "role_id": rid(R.DBA)},
        headers=hdr(it),
    )
    assert r.status_code == 403
    await invite(api, t, it, "viewer@example.com", R.VIEWER)  # allowed


async def test_viewer_cannot_invite_or_list(api: AsyncClient, db: AsyncSession) -> None:
    t, _ = await company(db)
    v = await make_user(db)
    await make_member(db, t, v, R.VIEWER)
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": "a@example.com", "role_id": rid(R.VIEWER)},
        headers=hdr(v),
    )
    assert r.status_code == 403
    assert (await api.get(f"/v1/tenants/{t.id}/invitations", headers=hdr(v))).status_code == 403


async def test_foreign_custom_role_is_rejected(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    foreign = await make_custom_role(db, await make_tenant(db), "x", {Permission.METADATA_READ})
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": "a@example.com", "role_id": str(foreign.id)},
        headers=hdr(owner),
    )
    assert r.status_code == 422


async def test_bad_email_is_422(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    r = await api.post(
        f"/v1/tenants/{t.id}/invitations",
        json={"email": "not-an-email", "role_id": rid(R.VIEWER)},
        headers=hdr(owner),
    )
    assert r.status_code == 422


async def test_revoke(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "a@example.com")
    inv_id = (await api.get(f"/v1/tenants/{t.id}/invitations", headers=hdr(owner))).json()[0]["id"]

    r = await api.delete(f"/v1/tenants/{t.id}/invitations/{inv_id}", headers=hdr(owner))
    assert r.status_code == 204
    assert (await api.post("/v1/invitations/preview", json={"token": token})).status_code == 404
    # Revoking twice: it is no longer pending.
    r = await api.delete(f"/v1/tenants/{t.id}/invitations/{inv_id}", headers=hdr(owner))
    assert r.status_code == 404
    assert await actions(db, t) == ["invitation.created", "invitation.revoked"]


async def test_cannot_revoke_other_companys_invitation(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    other, other_owner = await company(db)
    await invite(api, other, other_owner, "a@example.com")
    inv = await db.scalar(select(Invitation).where(Invitation.tenant_id == other.id))
    assert inv is not None
    r = await api.delete(f"/v1/tenants/{t.id}/invitations/{inv.id}", headers=hdr(owner))
    assert r.status_code == 404


# ---- preview / accept -------------------------------------------------------------------------


async def test_preview_needs_no_sign_in(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "new@example.com", R.BACKEND_DEV)
    r = await api.post("/v1/invitations/preview", json={"token": token})
    assert r.status_code == 200
    assert r.json() | {"expires_at": None} == {
        "tenant_name": "Sharma Textiles",
        "role_name": "Backend Developer",
        "email": "new@example.com",
        "invited_by_name": "Anil Sharma",
        "expires_at": None,
    }


async def test_unknown_token_is_404(api: AsyncClient) -> None:
    r = await api.post("/v1/invitations/preview", json={"token": "x" * 40})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "invitation_invalid"


async def test_accept_creates_membership(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "new@example.com", R.DBA)
    new = await make_user(db, email="NEW@example.com")

    r = await api.post("/v1/invitations/accept", json={"token": token}, headers=hdr(new))
    assert r.status_code == 200, r.text
    assert r.json() == {"tenant_id": str(t.id), "tenant_name": "Sharma Textiles", "role_key": "dba"}

    access = await resolve_access(db, user_id=new.id, tenant_id=t.id)
    assert access is not None and access.role_key == "dba"
    member = await db.scalar(select(TenantMember).where(TenantMember.user_id == new.id))
    assert member is not None and member.invited_by == owner.id
    assert await actions(db, t) == ["invitation.created", "invitation.accepted"]

    # The link is single-use.
    r = await api.post("/v1/invitations/accept", json={"token": token}, headers=hdr(new))
    assert r.status_code == 404


async def test_accept_requires_sign_in(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "new@example.com")
    r = await api.post("/v1/invitations/accept", json={"token": token})
    assert r.status_code == 401


async def test_accept_with_wrong_email_is_403(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "intended@example.com")
    someone_else = await make_user(db)
    r = await api.post("/v1/invitations/accept", json={"token": token}, headers=hdr(someone_else))
    assert r.status_code == 403
    # Still usable by the right person.
    assert (await api.post("/v1/invitations/preview", json={"token": token})).status_code == 200


async def test_expired_invitation_cannot_be_accepted(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "late@example.com")
    inv = await db.scalar(select(Invitation).where(Invitation.tenant_id == t.id))
    assert inv is not None
    inv.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    late = await make_user(db, email="late@example.com")
    r = await api.post("/v1/invitations/accept", json={"token": token}, headers=hdr(late))
    assert r.status_code == 404


async def test_suspended_company_invitation_is_dead(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    token = await invite(api, t, owner, "a@example.com")
    t.status = TenantStatus.SUSPENDED
    await db.flush()
    assert (await api.post("/v1/invitations/preview", json={"token": token})).status_code == 404
