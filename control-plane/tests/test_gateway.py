"""Gateway: a real server in the test, a fake connector with a real Ed25519 key, real WebSocket."""

import asyncio
import base64
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.gateway.hub import get_hub
from app.gateway.protocol import CloseCode, signed_payload
from app.models import Connector, Datasource, Tenant, User
from app.models.enums import ConnectorStatus
from app.rbac.catalog import SystemRole
from tests.factories import make_env, make_member, make_tenant, make_user

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def public_key_of(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "ed25519:" + base64.b64encode(raw).decode()


def sign(key: Ed25519PrivateKey, nonce: str, connector_id: str) -> str:
    return base64.b64encode(key.sign(signed_payload(nonce, connector_id))).decode()


DB_REPORT = [
    {
        "local_name": "orders-db",
        "engine": "postgres",
        "version": "16.4",
        "reachable": True,
        "catalog": {"databases": [{"name": "orders", "size_bytes": 1024, "tables": 3}]},
    },
    {"local_name": "inventory", "engine": "mysql", "version": "8.0.39", "reachable": False},
]


# ---- fixtures ----------------------------------------------------------------------------------


class _Shared:
    """The gateway and the test share ONE rolled-back session here (production opens a session
    per step). An AsyncSession must not be used by two coroutines at once, so both sides take
    this lock. A fresh lock per test: each test runs in its own event loop."""

    lock = asyncio.Lock()


def session_lock() -> asyncio.Lock:
    return _Shared.lock


@pytest.fixture
async def ws_url(db: AsyncSession, api: AsyncClient) -> AsyncIterator[str]:
    """Serve the real app on a free port; the gateway shares the test's rolled-back session."""
    from app.core.db import get_session_factory
    from app.main import app

    _Shared.lock = asyncio.Lock()

    @asynccontextmanager
    async def shared() -> AsyncIterator[AsyncSession]:
        async with session_lock():
            yield db

    app.dependency_overrides[get_session_factory] = lambda: shared
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)
    try:
        yield f"ws://127.0.0.1:{port}/v1/connectors/stream"
    finally:
        server.should_exit = True
        await task


class Company:
    def __init__(self, tenant: Tenant, user: User) -> None:
        self.tenant = tenant
        self.user = user


async def company(db: AsyncSession, role: SystemRole = R.DBA) -> Company:
    t = await make_tenant(db)
    u = await make_user(db)
    await make_member(db, t, u, role)
    await make_env(db, t, "production", prod=True)  # where reported databases land
    return Company(t, u)


async def enrolled_connector(api: AsyncClient, c: Company) -> tuple[str, Ed25519PrivateKey]:
    r = await api.post(
        f"/v1/tenants/{c.tenant.id}/connectors", json={"name": "Office"}, headers=hdr(c.user)
    )
    token = r.json()["enrollment"]["token"]
    key = Ed25519PrivateKey.generate()
    r = await api.post(
        "/v1/connectors/enroll",
        json={"token": token, "public_key": public_key_of(key), "version": "0.1.0"},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["connector_id"]), key


async def handshake(
    url: str,
    connector_id: str,
    key: Ed25519PrivateKey,
    databases: list[dict[str, Any]] | None = None,
) -> ClientConnection:
    ws = await connect(url)
    challenge = json.loads(await ws.recv())
    assert challenge["type"] == "challenge" and len(challenge["nonce"]) >= 32
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "connector_id": connector_id,
                "signature": sign(key, challenge["nonce"], connector_id),
                "version": "0.2.0",
                "databases": databases or [],
            }
        )
    )
    return ws


async def close_code(ws: ClientConnection) -> int | None:
    with pytest.raises(ConnectionClosed) as info:
        while True:
            await asyncio.wait_for(ws.recv(), timeout=5)
    return info.value.rcvd.code if info.value.rcvd else None


async def connector_row(db: AsyncSession, connector_id: str) -> Connector:
    # populate_existing: re-read this row now (the gateway changed it), without expiring the
    # other objects the test still holds.
    async with session_lock():
        row = await db.scalar(
            select(Connector)
            .where(Connector.id == connector_id)
            .execution_options(populate_existing=True)
        )
    assert row is not None
    return row


async def wait_until(predicate: Any, seconds: float = 3) -> None:
    for _ in range(int(seconds / 0.05)):
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


# ---- handshake -------------------------------------------------------------------------------


async def test_good_handshake_goes_online_and_syncs_databases(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)

    ws = await handshake(ws_url, cid, key, DB_REPORT)
    welcome = json.loads(await ws.recv())
    assert welcome == {"type": "welcome", "heartbeat_seconds": 20}

    row = await connector_row(db, cid)
    assert row.status == ConnectorStatus.ONLINE and row.version == "0.2.0"
    assert row.last_seen_at is not None
    assert get_hub().is_online(row.id)

    r = await api.get(f"/v1/tenants/{c.tenant.id}/datasources", headers=hdr(c.user))
    by_name = {d["local_name"]: d for d in r.json()}
    assert by_name["orders-db"]["status"] == "connected"
    assert by_name["inventory"]["status"] == "error"
    assert by_name["orders-db"]["connector"]["status"] == "online"

    await ws.close()

    async def offline() -> bool:
        return (await connector_row(db, cid)).status == ConnectorStatus.OFFLINE

    await wait_until(offline)
    assert not get_hub().is_online(row.id)


async def test_wrong_key_is_rejected(ws_url: str, api: AsyncClient, db: AsyncSession) -> None:
    c = await company(db)
    cid, _ = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, Ed25519PrivateKey.generate())
    assert await close_code(ws) == CloseCode.AUTH_FAILED
    assert (await connector_row(db, cid)).status == ConnectorStatus.OFFLINE


async def test_unknown_connector_gets_the_same_answer(ws_url: str) -> None:
    ws = await handshake(
        ws_url, "00000000-0000-4000-8000-000000000000", Ed25519PrivateKey.generate()
    )
    assert await close_code(ws) == CloseCode.AUTH_FAILED


async def test_signature_for_another_nonce_cannot_be_replayed(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await connect(ws_url)
    await ws.recv()  # the real challenge is ignored; an old signature is sent instead
    old = sign(key, "a-nonce-from-an-earlier-connection-0123456789", cid)
    await ws.send(json.dumps({"type": "hello", "connector_id": cid, "signature": old}))
    assert await close_code(ws) == CloseCode.AUTH_FAILED


async def test_revoked_connector_cannot_connect(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    r = await api.post(f"/v1/tenants/{c.tenant.id}/connectors/{cid}/revoke", headers=hdr(c.user))
    assert r.status_code == 200
    ws = await handshake(ws_url, cid, key)
    assert await close_code(ws) == CloseCode.AUTH_FAILED


async def test_garbage_instead_of_hello(ws_url: str) -> None:
    ws = await connect(ws_url)
    await ws.recv()
    await ws.send("not json")
    assert await close_code(ws) == CloseCode.BAD_MESSAGE


async def test_no_hello_in_time(ws_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.gateway.HANDSHAKE_TIMEOUT_SECONDS", 0.3)
    ws = await connect(ws_url)
    await ws.recv()
    assert await close_code(ws) == CloseCode.HANDSHAKE_TIMEOUT


# ---- live link -------------------------------------------------------------------------------


async def test_revoking_drops_the_live_link(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key)
    await ws.recv()  # welcome
    r = await api.post(f"/v1/tenants/{c.tenant.id}/connectors/{cid}/revoke", headers=hdr(c.user))
    assert r.status_code == 200
    assert await close_code(ws) == CloseCode.REVOKED
    assert (await connector_row(db, cid)).status == ConnectorStatus.REVOKED


async def test_reconnect_replaces_the_old_link_and_stays_online(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    first = await handshake(ws_url, cid, key)
    await first.recv()
    second = await handshake(ws_url, cid, key)
    await second.recv()
    assert await close_code(first) == CloseCode.REPLACED
    await asyncio.sleep(0.2)
    assert (await connector_row(db, cid)).status == ConnectorStatus.ONLINE
    await second.close()


async def test_report_updates_databases(ws_url: str, api: AsyncClient, db: AsyncSession) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key, DB_REPORT[:1])
    await ws.recv()
    await ws.send(json.dumps({"type": "report", "databases": DB_REPORT}))

    async def two() -> bool:
        async with session_lock():
            rows = (
                await db.scalars(select(Datasource).where(Datasource.connector_id == cid))
            ).all()
        return len(rows) == 2

    await wait_until(two)
    await ws.close()
    async with session_lock():
        orders = await db.scalar(
            select(Datasource)
            .where(Datasource.connector_id == cid, Datasource.local_name == "orders-db")
            .execution_options(populate_existing=True)
        )
    assert orders is not None and orders.catalog is not None
    assert orders.catalog["databases"] == [{"name": "orders", "size_bytes": 1024, "tables": 3}]


async def test_unknown_message_closes_the_link(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key)
    await ws.recv()
    await ws.send(json.dumps({"type": "run_sql", "sql": "drop table orders"}))
    assert await close_code(ws) == CloseCode.BAD_MESSAGE


# ---- on-demand check (request / response through the hub) ----------------------------------


async def answer_next_request(ws: ClientConnection, reply: dict[str, Any] | None) -> dict[str, Any]:
    """Wait for one request; send `reply` (None = stay silent). Returns the request."""
    while True:
        msg = json.loads(await ws.recv())
        if msg["type"] == "request":
            if reply is not None:
                await ws.send(json.dumps({"type": "response", "id": msg["id"], **reply}))
            return dict(msg)


async def test_check_asks_the_connector_and_stores_the_answer(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key, DB_REPORT)
    await ws.recv()
    ds = await db.scalar(select(Datasource).where(Datasource.local_name == "inventory"))
    assert ds is not None and ds.tenant_id == c.tenant.id

    fixed = {**DB_REPORT[1], "reachable": True, "version": "8.0.40"}
    responder = asyncio.create_task(answer_next_request(ws, {"ok": True, "result": fixed}))
    r = await api.post(f"/v1/tenants/{c.tenant.id}/datasources/{ds.id}/check", headers=hdr(c.user))
    request = await responder
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "connected" and r.json()["version"] == "8.0.40"
    assert request["tool"] == "probe" and request["args"] == {"datasource": "inventory"}
    await ws.close()


async def test_check_reports_tool_errors_and_timeouts(
    ws_url: str, api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key, DB_REPORT)
    await ws.recv()
    ds = await db.scalar(select(Datasource).where(Datasource.local_name == "orders-db"))
    assert ds is not None
    url = f"/v1/tenants/{c.tenant.id}/datasources/{ds.id}/check"

    failing = {"ok": False, "error": {"code": "unreachable", "message": "Connection refused"}}
    responder = asyncio.create_task(answer_next_request(ws, failing))
    r = await api.post(url, headers=hdr(c.user))
    await responder
    assert r.status_code == 502 and r.json()["error"]["message"] == "Connection refused"

    monkeypatch.setattr("app.api.datasources.CHECK_TIMEOUT_SECONDS", 0.3)
    responder = asyncio.create_task(answer_next_request(ws, None))
    r = await api.post(url, headers=hdr(c.user))
    await responder
    assert r.status_code == 504 and r.json()["error"]["code"] == "connector_timeout"
    await ws.close()


async def test_check_when_offline_and_across_companies(
    ws_url: str, api: AsyncClient, db: AsyncSession
) -> None:
    c = await company(db)
    cid, key = await enrolled_connector(api, c)
    ws = await handshake(ws_url, cid, key, DB_REPORT)
    await ws.recv()
    ds = await db.scalar(select(Datasource).where(Datasource.local_name == "orders-db"))
    assert ds is not None

    other = await company(db)
    r = await api.post(
        f"/v1/tenants/{other.tenant.id}/datasources/{ds.id}/check", headers=hdr(other.user)
    )
    assert r.status_code == 404, "another company must not even learn the database exists"

    await ws.close()

    async def offline() -> bool:
        return not get_hub().is_online((await connector_row(db, cid)).id)

    await wait_until(offline)
    r = await api.post(f"/v1/tenants/{c.tenant.id}/datasources/{ds.id}/check", headers=hdr(c.user))
    assert r.status_code == 409 and "offline" in r.json()["error"]["message"]
