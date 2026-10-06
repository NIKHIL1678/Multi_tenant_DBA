"""Sign-up, sign-in, access tokens, refresh rotation, reuse detection and sign-out."""

from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token
from app.core.config import get_settings
from app.models import AuthSession, User
from app.models.enums import UserStatus

PASSWORD = "correct-horse-battery"


async def signup(api: AsyncClient, email: str = "priya@sharma.example.com") -> str:
    r = await api.post(
        "/v1/auth/signup", json={"email": email, "password": PASSWORD, "full_name": "Priya"}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_signup_returns_token_and_sets_httponly_cookie(api: AsyncClient) -> None:
    r = await api.post(
        "/v1/auth/signup",
        json={"email": "a@example.com", "password": PASSWORD, "full_name": " Asha "},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    cookie = r.headers["set-cookie"].lower()
    assert "zdba_refresh=" in cookie
    assert "httponly" in cookie
    assert "path=/v1/auth" in cookie

    me = await api.get("/v1/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["full_name"] == "Asha"


async def test_password_is_hashed_never_stored(api: AsyncClient, db: AsyncSession) -> None:
    await signup(api, "hash@example.com")
    user = await db.scalar(select(User).where(User.email == "hash@example.com"))
    assert user is not None and user.password_hash is not None
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


async def test_signup_rejects_duplicate_email_any_case(api: AsyncClient) -> None:
    await signup(api, "dup@example.com")
    r = await api.post(
        "/v1/auth/signup",
        json={"email": "DUP@example.com", "password": PASSWORD, "full_name": "X"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_signup_validates_input(api: AsyncClient) -> None:
    r = await api.post(
        "/v1/auth/signup", json={"email": "not-an-email", "password": "short", "full_name": ""}
    )
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"email", "password", "full_name"} <= fields


async def test_login_success_and_failures_look_the_same(api: AsyncClient, db: AsyncSession) -> None:
    await signup(api, "login@example.com")
    ok = await api.post("/v1/auth/login", json={"email": "Login@Example.com", "password": PASSWORD})
    assert ok.status_code == 200

    wrong_pw = await api.post(
        "/v1/auth/login", json={"email": "login@example.com", "password": "x"}
    )
    no_user = await api.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "x"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


async def test_disabled_user_cannot_login(api: AsyncClient, db: AsyncSession) -> None:
    await signup(api, "off@example.com")
    user = await db.scalar(select(User).where(User.email == "off@example.com"))
    assert user is not None
    user.status = UserStatus.DISABLED
    await db.flush()
    r = await api.post("/v1/auth/login", json={"email": "off@example.com", "password": PASSWORD})
    assert r.status_code == 401


async def test_bad_tokens_are_rejected(api: AsyncClient, db: AsyncSession) -> None:
    token = await signup(api, "tok@example.com")
    user = await db.scalar(select(User).where(User.email == "tok@example.com"))
    assert user is not None

    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    expired, _ = create_access_token(user.id, now=datetime.now(UTC) - timedelta(hours=1))
    s = get_settings()
    wrong_key = jwt.encode(
        {
            "sub": str(user.id),
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "typ": "access",
        },
        "some-other-secret-that-is-long-enough-123",
        algorithm="HS256",
    )
    for bad in (tampered, expired, wrong_key, "garbage"):
        r = await api.get("/v1/me", headers=bearer(bad))
        assert r.status_code == 401, bad
    r = await api.get("/v1/me", headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 401


async def test_refresh_rotates_the_cookie(api: AsyncClient) -> None:
    await signup(api, "rot@example.com")
    first = api.cookies.get("zdba_refresh")
    r = await api.post("/v1/auth/refresh")
    assert r.status_code == 200
    second = api.cookies.get("zdba_refresh")
    assert first and second and first != second
    assert (await api.get("/v1/me", headers=bearer(r.json()["access_token"]))).status_code == 200


async def test_reusing_an_old_refresh_token_signs_out_everywhere(
    api: AsyncClient, db: AsyncSession
) -> None:
    await signup(api, "theft@example.com")
    stolen = api.cookies.get("zdba_refresh")
    assert (await api.post("/v1/auth/refresh")).status_code == 200  # legit rotation
    current = api.cookies.get("zdba_refresh")

    api.cookies.set("zdba_refresh", stolen or "", path="/v1/auth")
    replay = await api.post("/v1/auth/refresh")
    assert replay.status_code == 401

    api.cookies.set("zdba_refresh", current or "", path="/v1/auth")
    assert (await api.post("/v1/auth/refresh")).status_code == 401  # family revoked

    user = await db.scalar(select(User).where(User.email == "theft@example.com"))
    assert user is not None
    active = await db.scalar(
        select(AuthSession.id).where(
            AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
        )
    )
    assert active is None


async def test_refresh_without_cookie_fails(api: AsyncClient) -> None:
    r = await api.post("/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


async def test_logout_revokes_session(api: AsyncClient) -> None:
    await signup(api, "bye@example.com")
    cookie = api.cookies.get("zdba_refresh")
    r = await api.post("/v1/auth/logout")
    assert r.status_code == 204
    api.cookies.set("zdba_refresh", cookie or "", path="/v1/auth")
    assert (await api.post("/v1/auth/refresh")).status_code == 401
