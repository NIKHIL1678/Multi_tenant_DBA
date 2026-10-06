import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.models.enums import MemberStatus, UserStatus
from app.rbac.catalog import SystemRole
from tests.factories import make_member, make_tenant, make_user


def hdr(email: str) -> dict[str, str]:
    return {"X-Dev-User": email}


async def test_me_requires_sign_in(api: AsyncClient) -> None:
    r = await api.get("/v1/me")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthenticated"
    assert err["request_id"] == r.headers["X-Request-ID"]


async def test_me_rejects_unknown_user(api: AsyncClient) -> None:
    r = await api.get("/v1/me", headers=hdr("nobody@example.test"))
    assert r.status_code == 401


async def test_me_rejects_disabled_user(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db, status=UserStatus.DISABLED)
    r = await api.get("/v1/me", headers=hdr(u.email))
    assert r.status_code == 401


async def test_me_lists_active_memberships_only(api: AsyncClient, db: AsyncSession) -> None:
    u = await make_user(db, full_name="Arjun Mehta")
    a, b, c = await make_tenant(db), await make_tenant(db), await make_tenant(db)
    await make_member(db, a, u, SystemRole.DBA)
    await make_member(db, b, u, SystemRole.VIEWER)
    await make_member(db, c, u, SystemRole.OWNER, status=MemberStatus.SUSPENDED)

    r = await api.get("/v1/me", headers=hdr(u.email.upper()))  # email is case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == u.email
    assert body["full_name"] == "Arjun Mehta"
    got = {(m["tenant_id"], m["role_key"]) for m in body["memberships"]}
    assert got == {(str(a.id), "dba"), (str(b.id), "viewer")}


async def test_dev_users_lists_active_users(api: AsyncClient, db: AsyncSession) -> None:
    active = await make_user(db)
    disabled = await make_user(db, status=UserStatus.DISABLED)
    emails = {u["email"] for u in (await api.get("/v1/dev/users")).json()}
    assert active.email in emails
    assert disabled.email not in emails


SECRET = SecretStr("x" * 40)


def test_dev_auth_is_refused_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth=True, jwt_secret=SECRET)


def test_short_or_missing_jwt_secret_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth=False, jwt_secret=SecretStr("too-short"))


async def test_cors_allows_dashboard_origin(api: AsyncClient) -> None:
    r = await api.options(
        "/v1/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Dev-User",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_unhandled_error_returns_json_with_request_id() -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error"
    assert "kaboom" not in r.text  # internals never leak to the client
    assert err["request_id"] == r.headers["X-Request-ID"]
