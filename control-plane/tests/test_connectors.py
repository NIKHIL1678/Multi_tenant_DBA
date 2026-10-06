"""Connectors API: create + install command, new token, enroll, rename, revoke, safety rules."""

import base64
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Connector, EnrollmentToken, Tenant, User
from app.models.enums import ActorType, ConnectorStatus, TenantStatus
from app.rbac.catalog import SystemRole
from tests.factories import make_datasource, make_env, make_member, make_tenant, make_user

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def public_key() -> str:
    return "ed25519:" + base64.b64encode(os.urandom(32)).decode()


async def company(db: AsyncSession, role: SystemRole = R.OWNER) -> tuple[Tenant, User]:
    t = await make_tenant(db)
    u = await make_user(db)
    await make_member(db, t, u, role)
    return t, u


def url(t: Tenant, suffix: str = "") -> str:
    return f"/v1/tenants/{t.id}/connectors{suffix}"


async def create(
    api: AsyncClient, t: Tenant, u: User, name: str = "Mumbai office"
) -> dict[str, Any]:
    r = await api.post(url(t), json={"name": name}, headers=hdr(u))
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def enroll(api: AsyncClient, token: str, version: str | None = "0.1.0") -> int:
    r = await api.post(
        "/v1/connectors/enroll",
        json={"token": token, "public_key": public_key(), "version": version},
    )
    return r.status_code


async def actions(db: AsyncSession, t: Tenant) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == t.id)))


# ---- create ---------------------------------------------------------------------------------


async def test_create_returns_command_and_stores_only_hash(
    api: AsyncClient, db: AsyncSession
) -> None:
    t, u = await company(db, R.DBA)
    body = await create(api, t, u, "  Mumbai   office ")
    c, e = body["connector"], body["enrollment"]
    assert c["name"] == "Mumbai office"
    assert c["status"] == "pending"
    assert c["enrollment_expires_at"] is not None
    assert e["token"].startswith("zcet_")
    assert f"ZIPZY_ENROLL_TOKEN={e['token']}" in e["command"]
    assert "docker run" in e["command"]

    rows = (await db.scalars(select(EnrollmentToken))).all()
    assert all(e["token"] not in r.token_hash for r in rows)
    audit = await db.scalar(select(AuditLog).where(AuditLog.tenant_id == t.id))
    assert audit is not None and audit.action == "connector.created"
    assert e["token"] not in str(audit.details)


async def test_viewer_cannot_create(api: AsyncClient, db: AsyncSession) -> None:
    t, v = await company(db, R.VIEWER)
    r = await api.post(url(t), json={"name": "x"}, headers=hdr(v))
    assert r.status_code == 403


async def test_duplicate_name_is_409(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    await create(api, t, u, "Office")
    r = await api.post(url(t), json={"name": "Office"}, headers=hdr(u))
    assert r.status_code == 409


async def test_list_and_get(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    body = await create(api, t, owner, "B office")
    await create(api, t, owner, "A office")
    other, other_owner = await company(db)
    await create(api, other, other_owner, "Secret")

    viewer = await make_user(db)
    await make_member(db, t, viewer, R.VIEWER)
    r = await api.get(url(t), headers=hdr(viewer))
    assert r.status_code == 200
    assert [c["name"] for c in r.json()] == ["A office", "B office"]
    assert "token" not in str(r.json())

    one = await api.get(url(t, f"/{body['connector']['id']}"), headers=hdr(viewer))
    assert one.status_code == 200 and one.json()["name"] == "B office"


async def test_other_companys_connector_is_404(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    other, other_owner = await company(db)
    cid = (await create(api, other, other_owner))["connector"]["id"]
    assert (await api.get(url(t, f"/{cid}"), headers=hdr(u))).status_code == 404
    assert (await api.post(url(t, f"/{cid}/revoke"), headers=hdr(u))).status_code == 404


# ---- enroll ---------------------------------------------------------------------------------


async def test_enroll_happy_path(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    body = await create(api, t, u)
    token, cid = body["enrollment"]["token"], body["connector"]["id"]

    key = public_key()
    r = await api.post(
        "/v1/connectors/enroll", json={"token": token, "public_key": key, "version": "0.1.0"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"connector_id": cid, "tenant_id": str(t.id)}

    c = await db.get(Connector, cid)
    assert c is not None
    await db.refresh(c)
    assert c.status == ConnectorStatus.OFFLINE
    assert c.public_key == key
    assert c.version == "0.1.0"

    row = await db.scalar(select(AuditLog).where(AuditLog.action == "connector.enrolled"))
    assert row is not None
    assert row.actor_type == ActorType.CONNECTOR and str(row.actor_id) == cid

    listed = (await api.get(url(t, f"/{cid}"), headers=hdr(u))).json()
    assert listed["status"] == "offline" and listed["enrollment_expires_at"] is None


async def test_token_works_only_once(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    token = (await create(api, t, u))["enrollment"]["token"]
    assert await enroll(api, token) == 200
    assert await enroll(api, token) == 401


async def test_unknown_token_is_401(api: AsyncClient) -> None:
    r = await api.post(
        "/v1/connectors/enroll", json={"token": "zcet_" + "x" * 40, "public_key": public_key()}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "enrollment_invalid"


async def test_expired_token_is_401(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    token = (await create(api, t, u))["enrollment"]["token"]
    row = await db.scalar(select(EnrollmentToken))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    assert await enroll(api, token) == 401


async def test_suspended_company_cannot_enroll(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    token = (await create(api, t, u))["enrollment"]["token"]
    t.status = TenantStatus.SUSPENDED
    await db.flush()
    assert await enroll(api, token) == 401


async def test_bad_public_key_is_422(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    token = (await create(api, t, u))["enrollment"]["token"]
    short = "ed25519:" + base64.b64encode(b"too-short").decode()
    for key in ("rsa:abc" + "x" * 20, short, "ed25519:!!!not-base64!!!" + "x" * 10):
        r = await api.post("/v1/connectors/enroll", json={"token": token, "public_key": key})
        assert r.status_code == 422, key
    assert await enroll(api, token) == 200  # still unused after the bad attempts


# ---- new token ------------------------------------------------------------------------------


async def test_new_token_replaces_old_one(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    body = await create(api, t, u)
    old, cid = body["enrollment"]["token"], body["connector"]["id"]

    r = await api.post(url(t, f"/{cid}/enrollment-token"), headers=hdr(u))
    assert r.status_code == 201
    new = r.json()["token"]
    assert new != old

    assert await enroll(api, old) == 401
    assert await enroll(api, new) == 200
    # Once installed, no more install commands.
    r = await api.post(url(t, f"/{cid}/enrollment-token"), headers=hdr(u))
    assert r.status_code == 409


# ---- rename / revoke ------------------------------------------------------------------------


async def test_rename(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    cid = (await create(api, t, u, "Old"))["connector"]["id"]
    await create(api, t, u, "Taken")

    r = await api.patch(url(t, f"/{cid}"), json={"name": "New"}, headers=hdr(u))
    assert r.status_code == 200 and r.json()["name"] == "New"
    r = await api.patch(url(t, f"/{cid}"), json={"name": "Taken"}, headers=hdr(u))
    assert r.status_code == 409
    assert (await actions(db, t)).count("connector.renamed") == 1


async def test_revoke_is_final(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    body = await create(api, t, u)
    token, cid = body["enrollment"]["token"], body["connector"]["id"]
    assert await enroll(api, token) == 200

    r = await api.post(url(t, f"/{cid}/revoke"), headers=hdr(u))
    assert r.status_code == 200
    assert r.json()["status"] == "revoked" and r.json()["revoked_at"] is not None
    c = await db.get(Connector, cid)
    assert c is not None
    await db.refresh(c)
    assert c.public_key is None

    assert (await api.post(url(t, f"/{cid}/revoke"), headers=hdr(u))).status_code == 409
    r = await api.post(url(t, f"/{cid}/enrollment-token"), headers=hdr(u))
    assert r.status_code == 409


async def test_revoking_pending_connector_kills_its_command(
    api: AsyncClient, db: AsyncSession
) -> None:
    t, u = await company(db)
    body = await create(api, t, u)
    r = await api.post(url(t, f"/{body['connector']['id']}/revoke"), headers=hdr(u))
    assert r.status_code == 200
    assert await enroll(api, body["enrollment"]["token"]) == 401


async def test_revoke_reports_datasource_count(api: AsyncClient, db: AsyncSession) -> None:
    t, u = await company(db)
    env = await make_env(db, t, "production", prod=True)
    ds = await make_datasource(db, t, env, created_by=u)
    r = await api.post(url(t, f"/{ds.connector_id}/revoke"), headers=hdr(u))
    assert r.status_code == 200
    assert r.json()["datasource_count"] == 1
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "connector.revoked"))
    assert row is not None and row.details is not None and row.details["datasources"] == 1


async def test_viewer_cannot_revoke(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    cid = (await create(api, t, owner))["connector"]["id"]
    v = await make_user(db)
    await make_member(db, t, v, R.VIEWER)
    assert (await api.post(url(t, f"/{cid}/revoke"), headers=hdr(v))).status_code == 403
