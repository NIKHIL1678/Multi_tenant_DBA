"""Collectors through the API: who may run them, what is stored, how failures are reported.

The hub is replaced by a fake that answers like a 0.4.0 connector (the real link is covered in
test_gateway.py and on the connector side).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.hub import ConnectorHub, RequestTimeoutError, ToolFailedError, get_hub
from app.gateway.protocol import ALLOWED_TOOLS
from app.models import Snapshot
from app.models.enums import Collector, DbEngine
from app.services import snapshots as svc
from tests.factories import make_custom_role, make_datasource, override_role
from tests.test_datasources import R, hdr, member, url, world

HEALTH = {
    "format": 1,
    "uptime_seconds": 3600,
    "connections": {"current": 12, "active": 3, "max": 151, "peak": 40},
    "cache_hit_ratio": 0.991,
    "throughput_per_second": 120.5,
    "throughput_unit": "queries",
    "deadlocks": 0,
    "slow_queries": 4,
    "temp_tables_on_disk_ratio": 0.02,
    "replication": {"is_replica": False, "lag_seconds": None},
    "settings": {"max_connections": "151", "slow_query_log": "OFF"},
    "some_future_field": {"ignored": True},
}
TABLES = {
    "total_tables": 2,
    "truncated": False,
    "tables": [
        {
            "schema": "zipzy_hrm",
            "name": "attendance",
            "engine": "InnoDB",
            "rows": 200_000,
            "data_bytes": 9_977_856,
            "index_bytes": 0,
            "free_bytes": 4_194_304,
            "dead_rows": None,
            "has_primary_key": True,
            "seq_scans": None,
            "index_scans": None,
        },
        {"schema": "zipzy_hrm", "name": "audit_log", "has_primary_key": False},
    ],
}
INDEXES = {
    "usage_since": "2026-10-01T00:00:00+00:00",
    "total_indexes": 2,
    "indexes": [
        {
            "schema": "zipzy_hrm",
            "table": "orders",
            "name": "by_status",
            "columns": ["status"],
            "unique": False,
            "primary": False,
            "scans": 0,
        },
        {
            "schema": "zipzy_hrm",
            "table": "orders",
            "name": "by_status_date",
            "columns": ["status", "created_at"],
            "unique": False,
            "primary": False,
            "scans": 12,
        },
    ],
    "unused": [
        {"schema": "zipzy_hrm", "table": "orders", "index": "by_status", "columns": ["status"]}
    ],
    "duplicates": [
        {
            "schema": "zipzy_hrm",
            "table": "orders",
            "index": "by_status",
            "columns": ["status"],
            "covered_by": "by_status_date",
        }
    ],
    "missing_primary_keys": [{"schema": "zipzy_hrm", "table": "audit_log", "rows": 10}],
}


class FakeHub:
    """Answers like a connector; records what was asked."""

    def __init__(self, answers: dict[str, Any] | None = None, *, online: bool = True) -> None:
        self.answers: dict[str, Any] = answers or {
            "health": HEALTH,
            "table_stats": TABLES,
            "indexes": INDEXES,
        }
        self.online = online
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def is_online(self, connector_id: uuid.UUID) -> bool:
        return self.online

    async def request(
        self, connector_id: uuid.UUID, tool: str, args: dict[str, Any], *, wait_seconds: float
    ) -> dict[str, Any]:
        assert tool in ALLOWED_TOOLS
        self.calls.append((tool, args))
        answer = self.answers[tool]
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


@pytest.fixture
def use_hub() -> Any:
    from app.main import app

    def install(hub: FakeHub) -> FakeHub:
        app.dependency_overrides[get_hub] = lambda: hub
        return hub

    return install  # the api fixture clears overrides afterwards


async def test_viewer_collects_and_reads_the_latest(
    api: AsyncClient, db: AsyncSession, use_hub: Any
) -> None:
    w = await world(db)
    viewer, _ = await member(db, w.t, R.VIEWER)
    hub = use_hub(FakeHub())
    ds = w.my_staging

    r = await api.get(url(w.t, f"/{ds.id}/snapshots"), headers=hdr(viewer))
    assert r.status_code == 200
    assert r.json() == {
        "datasource_id": str(ds.id),
        "health": None,
        "table_stats": None,
        "indexes": None,
        "errors": [],
    }

    r = await api.post(url(w.t, f"/{ds.id}/collect"), headers=hdr(viewer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == []
    assert body["health"]["data"]["connections"]["max"] == 151
    assert "some_future_field" not in body["health"]["data"]
    assert body["table_stats"]["data"]["tables"][0]["schema"] == "zipzy_hrm"
    assert body["indexes"]["data"]["duplicates"][0]["covered_by"] == "by_status_date"
    assert sorted(t for t, _ in hub.calls) == ["health", "indexes", "table_stats"]
    assert all(args == {"datasource": ds.local_name} for _, args in hub.calls)

    again = await api.get(url(w.t, f"/{ds.id}/snapshots"), headers=hdr(viewer))
    assert again.json()["indexes"] == body["indexes"]


async def test_recent_answers_are_reused(api: AsyncClient, db: AsyncSession, use_hub: Any) -> None:
    w = await world(db)
    hub = use_hub(FakeHub())
    path = url(w.t, f"/{w.my_staging.id}/collect")
    await api.post(path, headers=hdr(w.owner))
    await api.post(path, headers=hdr(w.owner), json={"collectors": ["health", "health"]})
    assert len(hub.calls) == 3, "a second click within 30 s does not ask the database again"


async def test_failures_are_per_collector(api: AsyncClient, db: AsyncSession, use_hub: Any) -> None:
    w = await world(db)
    use_hub(
        FakeHub(
            {
                "health": HEALTH,
                "table_stats": ToolFailedError("unknown_tool", "no such tool"),
                "indexes": {"total_indexes": "lots"},  # wrong shape
            }
        )
    )
    r = await api.post(url(w.t, f"/{w.my_staging.id}/collect"), headers=hdr(w.owner))
    assert r.status_code == 200
    body = r.json()
    assert body["health"] is not None and body["table_stats"] is None
    codes = {e["collector"]: e["code"] for e in body["errors"]}
    assert codes == {"table_stats": "outdated_connector", "indexes": "bad_answer"}
    assert "0.4.0" in next(e["message"] for e in body["errors"] if e["collector"] == "table_stats")

    use_hub(FakeHub({"health": RequestTimeoutError(), "table_stats": TABLES, "indexes": INDEXES}))
    r = await api.post(
        url(w.t, f"/{w.my_staging.id}/collect"),
        headers=hdr(w.owner),
        json={"collectors": ["table_stats"]},
    )
    assert r.json()["errors"] == [] and r.json()["table_stats"] is not None


async def test_offline_and_unsupported(api: AsyncClient, db: AsyncSession, use_hub: Any) -> None:
    w = await world(db)
    hub = use_hub(FakeHub(online=False))
    r = await api.post(url(w.t, f"/{w.my_staging.id}/collect"), headers=hdr(w.owner))
    assert r.status_code == 409 and "offline" in r.json()["error"]["message"]

    mongo = await make_datasource(db, w.t, w.staging, created_by=w.owner, engine=DbEngine.MONGODB)
    hub.online = True
    r = await api.post(url(w.t, f"/{mongo.id}/collect"), headers=hdr(w.owner))
    assert r.status_code == 200
    assert {e["code"] for e in r.json()["errors"]} == {"unsupported"}
    assert hub.calls == []


async def test_visibility_follows_the_environment(
    api: AsyncClient, db: AsyncSession, use_hub: Any
) -> None:
    w = await world(db)
    other = await world(db)
    hub = use_hub(FakeHub())
    blind = await make_custom_role(db, w.t, "no-access", set())
    contractor, m = await member(db, w.t, R.BACKEND_DEV)
    await override_role(db, m, w.prod, blind.id)

    for who in (contractor, other.owner):
        for method, suffix in (("get", "snapshots"), ("post", "collect")):
            r = await api.request(method, url(w.t, f"/{w.pg_prod.id}/{suffix}"), headers=hdr(who))
            assert r.status_code == 404, (who.email, suffix)
    assert hub.calls == []


async def test_old_snapshots_expire_and_go_with_the_datasource(db: AsyncSession) -> None:
    w = await world(db)
    ds = w.my_staging
    old = Snapshot(
        tenant_id=w.t.id,
        datasource_id=ds.id,
        collector=Collector.HEALTH,
        data=HEALTH,
        collected_at=datetime.now(UTC) - timedelta(days=svc.RETENTION_DAYS + 1),
    )
    db.add(old)
    await db.flush()
    await svc.store(db, ds, Collector.HEALTH, HEALTH)
    await svc.store(db, ds, Collector.INDEXES, INDEXES)
    rows = (await db.scalars(select(Snapshot).where(Snapshot.datasource_id == ds.id))).all()
    assert old not in rows and len(rows) == 2
    assert set(await svc.latest(db, ds.id)) == {Collector.HEALTH, Collector.INDEXES}

    await db.delete(ds)
    await db.flush()
    left = await db.scalar(
        select(func.count()).select_from(Snapshot).where(Snapshot.datasource_id == ds.id)
    )
    assert left == 0


async def test_only_allow_listed_tools_can_be_requested() -> None:
    assert {"probe", "health", "table_stats", "indexes"} == set(ALLOWED_TOOLS)
    with pytest.raises(ValueError, match="not allowed"):
        await ConnectorHub().request(uuid.uuid4(), "run_sql", {"sql": "drop table x"})
