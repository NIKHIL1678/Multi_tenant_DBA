from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import health
from app.core.db import get_engine
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await get_engine().dispose()


async def test_liveness(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readiness_when_database_is_up(client: AsyncClient) -> None:
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "up"}


async def test_readiness_when_database_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> str:
        raise OSError("connection refused")

    monkeypatch.setattr(health, "check_database", broken)
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "database": "down"}


async def test_request_id_is_generated(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert len(r.headers["X-Request-ID"]) == 32


async def test_request_id_is_echoed_when_safe(client: AsyncClient) -> None:
    r = await client.get("/healthz", headers={"X-Request-ID": "trace-abc_123"})
    assert r.headers["X-Request-ID"] == "trace-abc_123"


async def test_unsafe_request_id_is_replaced(client: AsyncClient) -> None:
    r = await client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(r.headers["X-Request-ID"]) == 32
