"""Audit log viewer: who may read it, isolation, filters, actor names and cursor paging."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import decode_cursor, encode_cursor
from app.models import AuditLog, Connector, Tenant, User
from app.models.enums import ActorType, ConnectorStatus
from app.rbac.catalog import SystemRole
from tests.factories import make_member, make_tenant, make_user

R = SystemRole
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def url(t: Tenant) -> str:
    return f"/v1/tenants/{t.id}/audit-log"


async def company(db: AsyncSession) -> tuple[Tenant, User]:
    t = await make_tenant(db)
    owner = await make_user(db, full_name="Anil Sharma")
    await make_member(db, t, owner, R.OWNER)
    return t, owner


async def add(db: AsyncSession, t: Tenant, action: str, *, minutes: int = 0, **kw: Any) -> AuditLog:
    fields: dict[str, Any] = {
        "tenant_id": t.id,
        "actor_type": ActorType.SYSTEM,
        "action": action,
        "created_at": T0 + timedelta(minutes=minutes),
    }
    fields.update(kw)
    row = AuditLog(**fields)
    db.add(row)
    await db.flush()
    return row


# ---- access ---------------------------------------------------------------------------------


async def test_who_can_read(api: AsyncClient, db: AsyncSession) -> None:
    t, _ = await company(db)
    allowed = {R.OWNER: 200, R.DBA: 200, R.IT_ADMIN: 200, R.BACKEND_DEV: 403, R.VIEWER: 403}
    for role, expected in allowed.items():
        u = await make_user(db)
        await make_member(db, t, u, role)
        assert (await api.get(url(t), headers=hdr(u))).status_code == expected, role
    outsider = await make_user(db)
    assert (await api.get(url(t), headers=hdr(outsider))).status_code == 404


async def test_only_own_company_rows(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    other, _ = await company(db)
    mine = await add(db, t, "tenant.renamed")
    await add(db, other, "tenant.renamed")
    r = await api.get(url(t), headers=hdr(owner))
    assert [e["id"] for e in r.json()["items"]] == [mine.id]


# ---- content --------------------------------------------------------------------------------


async def test_entry_shows_actor_names(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    c = Connector(
        tenant_id=t.id, name="Mumbai office", status=ConnectorStatus.OFFLINE, created_by=owner.id
    )
    db.add(c)
    await db.flush()
    target = uuid.uuid4()
    await add(
        db,
        t,
        "member.role_changed",
        minutes=1,
        actor_type=ActorType.USER,
        actor_id=owner.id,
        target_type="member",
        target_id=target,
        details={"from": "viewer", "to": "dba"},
        ip_address="10.0.0.7",
        request_id="req-1",
    )
    await add(db, t, "connector.enrolled", minutes=2, actor_type=ActorType.CONNECTOR, actor_id=c.id)
    gone = uuid.uuid4()  # a user who no longer exists: the row stays, names are just empty
    await add(db, t, "tenant.renamed", minutes=3, actor_type=ActorType.USER, actor_id=gone)

    items = (await api.get(url(t), headers=hdr(owner))).json()["items"]
    by_action = {e["action"]: e for e in items}
    changed = by_action["member.role_changed"]
    assert changed["actor"] == {
        "type": "user",
        "id": str(owner.id),
        "email": owner.email,
        "name": "Anil Sharma",
    }
    assert changed["target_id"] == str(target)
    assert changed["details"] == {"from": "viewer", "to": "dba"}
    assert (changed["ip_address"], changed["request_id"]) == ("10.0.0.7", "req-1")
    assert by_action["connector.enrolled"]["actor"]["name"] == "Mumbai office"
    assert by_action["tenant.renamed"]["actor"] == {
        "type": "user",
        "id": str(gone),
        "email": None,
        "name": None,
    }
    assert items[0]["action"] == "tenant.renamed"  # newest first


async def test_real_actions_show_up(api: AsyncClient, db: AsyncSession) -> None:
    """End to end: an API change is visible in the log with the same request id."""
    t, owner = await company(db)
    r = await api.patch(f"/v1/tenants/{t.id}", json={"name": "Renamed Co"}, headers=hdr(owner))
    assert r.status_code == 200
    items = (await api.get(url(t), headers=hdr(owner))).json()["items"]
    assert items[0]["action"] == "tenant.renamed"
    assert items[0]["request_id"] == r.headers["X-Request-ID"]


# ---- filters --------------------------------------------------------------------------------


async def test_filters(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    someone = uuid.uuid4()
    target = uuid.uuid4()
    a = await add(
        db, t, "member.role_changed", minutes=1, actor_type=ActorType.USER, actor_id=someone
    )
    b = await add(db, t, "member.suspended", minutes=2, target_type="member", target_id=target)
    c = await add(db, t, "connector.created", minutes=3)
    h = hdr(owner)

    async def ids(**params: str) -> list[int]:
        r = await api.get(url(t), params=params, headers=h)
        assert r.status_code == 200, r.text
        return [e["id"] for e in r.json()["items"]]

    assert await ids(action="member.") == [b.id, a.id]  # prefix
    assert await ids(action="member.suspended") == [b.id]  # exact
    assert await ids(action="member") == []  # not a prefix without the dot
    assert await ids(actor_id=str(someone)) == [a.id]
    assert await ids(actor_type="user") == [a.id]
    assert await ids(target_type="member", target_id=str(target)) == [b.id]
    since = (T0 + timedelta(minutes=2)).isoformat()
    until = (T0 + timedelta(minutes=3)).isoformat()
    assert await ids(since=since) == [c.id, b.id]
    assert await ids(since=since, until=until) == [b.id]


async def test_action_prefix_is_not_a_wildcard(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    await add(db, t, "member.suspended")
    r = await api.get(url(t), params={"action": "%."}, headers=hdr(owner))
    assert r.json()["items"] == []


async def test_bad_filters_are_422(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    for params in ({"actor_type": "robot"}, {"limit": "0"}, {"limit": "201"}, {"since": "x"}):
        assert (await api.get(url(t), params=params, headers=hdr(owner))).status_code == 422


# ---- paging ---------------------------------------------------------------------------------


async def test_cursor_paging_walks_everything_once(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    made = [await add(db, t, f"thing.{i}", minutes=i // 2) for i in range(7)]  # with ties
    expected = [row.id for row in sorted(made, key=lambda r: (r.created_at, r.id), reverse=True)]

    seen: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = {"limit": "3"} | ({"cursor": cursor} if cursor else {})
        body = (await api.get(url(t), params=params, headers=hdr(owner))).json()
        seen += [e["id"] for e in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == expected
    assert pages == 3


async def test_new_rows_do_not_shift_later_pages(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    for i in range(4):
        await add(db, t, f"old.{i}", minutes=i)
    first = (await api.get(url(t), params={"limit": "2"}, headers=hdr(owner))).json()
    await add(db, t, "brand.new", minutes=99)  # arrives while the user is reading page 1
    second = (
        await api.get(
            url(t), params={"limit": "2", "cursor": first["next_cursor"]}, headers=hdr(owner)
        )
    ).json()
    assert [e["action"] for e in second["items"]] == ["old.1", "old.0"]


async def test_bad_cursor_is_422(api: AsyncClient, db: AsyncSession) -> None:
    t, owner = await company(db)
    r = await api.get(url(t), params={"cursor": "not-a-cursor!!"}, headers=hdr(owner))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_cursor"


def test_cursor_round_trip() -> None:
    at = datetime(2026, 10, 6, 5, 30, 12, 123456, tzinfo=UTC)
    assert decode_cursor(encode_cursor(at, 42)) == (at, 42)
