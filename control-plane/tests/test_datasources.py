"""Datasources: per-environment visibility, move/delete rules, and syncing connector reports."""

import typing
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Connector, Datasource, Environment, Tenant, TenantMember, User
from app.models.enums import ConnectorStatus, DatasourceStatus, DbEngine
from app.rbac.catalog import Permission, SystemRole
from app.rbac.service import environments_with_permission
from app.schemas.datasources import ReportedDatasource
from app.services.datasources import ConnectorRevokedError, sync_from_connector
from tests.factories import (
    make_custom_role,
    make_datasource,
    make_env,
    make_member,
    make_tenant,
    make_user,
    override_role,
)

R = SystemRole


def hdr(user: User) -> dict[str, str]:
    return {"X-Dev-User": user.email}


def url(t: Tenant, suffix: str = "") -> str:
    return f"/v1/tenants/{t.id}/datasources{suffix}"


class World(typing.NamedTuple):
    t: Tenant
    owner: User
    prod: Environment
    staging: Environment
    pg_prod: Datasource
    my_staging: Datasource


async def world(db: AsyncSession) -> World:
    """A company with production + staging and one database in each."""
    t = await make_tenant(db)
    owner = await make_user(db)
    await make_member(db, t, owner, R.OWNER)
    prod = await make_env(db, t, "production", prod=True)
    staging = await make_env(db, t, "staging")
    pg_prod = await make_datasource(db, t, prod, created_by=owner, engine=DbEngine.POSTGRES)
    my_staging = await make_datasource(db, t, staging, created_by=owner, engine=DbEngine.MYSQL)
    return World(t, owner, prod, staging, pg_prod, my_staging)


async def member(db: AsyncSession, t: Tenant, role: SystemRole) -> tuple[User, TenantMember]:
    u = await make_user(db)
    return u, await make_member(db, t, u, role)


# ---- visibility -----------------------------------------------------------------------------


async def test_list_shows_connector_and_environment(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    viewer, _ = await member(db, w.t, R.VIEWER)
    other = await world(db)  # another company's databases must never appear

    r = await api.get(url(w.t), headers=hdr(viewer))
    assert r.status_code == 200
    body = r.json()
    assert {d["id"] for d in body} == {str(w.pg_prod.id), str(w.my_staging.id)}
    pg = next(d for d in body if d["engine"] == "postgres")
    assert pg["environment"] == {"id": str(w.prod.id), "name": "production", "is_production": True}
    assert pg["connector"]["status"] == "pending"
    assert str(other.pg_prod.id) not in str(body)


async def test_filters(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    h = hdr(w.owner)
    by_env = await api.get(url(w.t), params={"environment_id": str(w.staging.id)}, headers=h)
    assert [d["id"] for d in by_env.json()] == [str(w.my_staging.id)]
    by_engine = await api.get(url(w.t), params={"engine": "postgres"}, headers=h)
    assert [d["id"] for d in by_engine.json()] == [str(w.pg_prod.id)]
    bad = await api.get(url(w.t), params={"engine": "oracle"}, headers=h)
    assert bad.status_code == 422


async def test_override_without_metadata_read_hides_production(
    api: AsyncClient, db: AsyncSession
) -> None:
    """A contractor who may work in staging but must not even see production."""
    w = await world(db)
    blind = await make_custom_role(db, w.t, "no-access", set())
    contractor, m = await member(db, w.t, R.BACKEND_DEV)
    await override_role(db, m, w.prod, blind.id)

    r = await api.get(url(w.t), headers=hdr(contractor))
    assert [d["id"] for d in r.json()] == [str(w.my_staging.id)]
    one = await api.get(url(w.t, f"/{w.pg_prod.id}"), headers=hdr(contractor))
    assert one.status_code == 404


async def test_override_can_also_grant_visibility(db: AsyncSession) -> None:
    w = await world(db)
    reader = await make_custom_role(db, w.t, "prod-reader", {Permission.METADATA_READ})
    nobody = await make_custom_role(db, w.t, "nobody", set())
    u, _ = await member(db, w.t, R.VIEWER)
    # Tenant role sees nothing; an override opens exactly one environment.
    m = await db.scalar(select(TenantMember).where(TenantMember.user_id == u.id))
    assert m is not None
    m.role_id = nobody.id
    await override_role(db, m, w.prod, reader.id)
    visible = await environments_with_permission(
        db, user_id=u.id, tenant_id=w.t.id, permission=Permission.METADATA_READ
    )
    assert visible == {w.prod.id}


async def test_override_with_foreign_role_grants_nothing(db: AsyncSession) -> None:
    w = await world(db)
    foreign = await make_custom_role(db, await make_tenant(db), "x", {Permission.METADATA_READ})
    nobody = await make_custom_role(db, w.t, "nobody", set())
    u, m = await member(db, w.t, R.VIEWER)
    m.role_id = nobody.id
    await override_role(db, m, w.prod, foreign.id)
    visible = await environments_with_permission(
        db, user_id=u.id, tenant_id=w.t.id, permission=Permission.METADATA_READ
    )
    assert visible == set()


async def test_outsider_gets_404(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    outsider = await make_user(db)
    assert (await api.get(url(w.t), headers=hdr(outsider))).status_code == 404


# ---- move -----------------------------------------------------------------------------------


async def test_dba_moves_between_non_production(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    qa = await make_env(db, w.t, "qa")
    dba, _ = await member(db, w.t, R.DBA)
    r = await api.patch(
        url(w.t, f"/{w.my_staging.id}"), json={"environment_id": str(qa.id)}, headers=hdr(dba)
    )
    assert r.status_code == 200, r.text
    assert r.json()["environment"]["name"] == "qa"
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "datasource.moved"))
    assert row is not None and row.details is not None
    assert (row.details["from"], row.details["to"]) == ("staging", "qa")


async def test_only_owner_can_take_out_of_production(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    dba, _ = await member(db, w.t, R.DBA)
    body = {"environment_id": str(w.staging.id)}
    r = await api.patch(url(w.t, f"/{w.pg_prod.id}"), json=body, headers=hdr(dba))
    assert r.status_code == 403
    r = await api.patch(url(w.t, f"/{w.pg_prod.id}"), json=body, headers=hdr(w.owner))
    assert r.status_code == 200
    # Moving INTO production is stricter, so a DBA may do that.
    r = await api.patch(
        url(w.t, f"/{w.pg_prod.id}"), json={"environment_id": str(w.prod.id)}, headers=hdr(dba)
    )
    assert r.status_code == 200


async def test_backend_dev_cannot_move(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    dev, _ = await member(db, w.t, R.BACKEND_DEV)
    r = await api.patch(
        url(w.t, f"/{w.my_staging.id}"),
        json={"environment_id": str(w.prod.id)},
        headers=hdr(dev),
    )
    assert r.status_code == 403


async def test_target_environment_must_allow_manage(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    dba, m = await member(db, w.t, R.DBA)
    await override_role(db, m, w.prod, R.VIEWER)  # DBA is only a viewer in production
    r = await api.patch(
        url(w.t, f"/{w.my_staging.id}"),
        json={"environment_id": str(w.prod.id)},
        headers=hdr(dba),
    )
    assert r.status_code == 403


async def test_move_to_other_companys_environment_is_404(
    api: AsyncClient, db: AsyncSession
) -> None:
    w = await world(db)
    foreign = await make_env(db, await make_tenant(db), "staging")
    r = await api.patch(
        url(w.t, f"/{w.my_staging.id}"),
        json={"environment_id": str(foreign.id)},
        headers=hdr(w.owner),
    )
    assert r.status_code == 404


async def test_move_to_same_environment_is_a_no_op(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    r = await api.patch(
        url(w.t, f"/{w.my_staging.id}"),
        json={"environment_id": str(w.staging.id)},
        headers=hdr(w.owner),
    )
    assert r.status_code == 200
    assert await db.scalar(select(AuditLog).where(AuditLog.tenant_id == w.t.id)) is None


# ---- delete ---------------------------------------------------------------------------------


async def test_delete_rules(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    dba, _ = await member(db, w.t, R.DBA)
    staging_id, prod_id = w.my_staging.id, w.pg_prod.id
    assert (await api.delete(url(w.t, f"/{prod_id}"), headers=hdr(dba))).status_code == 403
    assert (await api.delete(url(w.t, f"/{staging_id}"), headers=hdr(dba))).status_code == 204
    assert (await api.delete(url(w.t, f"/{prod_id}"), headers=hdr(w.owner))).status_code == 204
    actions = list(await db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == w.t.id)))
    assert actions == ["datasource.deleted", "datasource.deleted"]


# ---- sync from connector reports ---------------------------------------------------------------


async def enrolled_connector(db: AsyncSession, t: Tenant, by: User) -> Connector:
    c = Connector(
        tenant_id=t.id,
        name=f"c-{uuid.uuid4().hex[:6]}",
        status=ConnectorStatus.OFFLINE,
        created_by=by.id,
    )
    db.add(c)
    await db.flush()
    return c


def rep(name: str, **kw: typing.Any) -> ReportedDatasource:
    fields: dict[str, typing.Any] = {"local_name": name, "engine": "postgres", "reachable": True}
    fields.update(kw)
    return ReportedDatasource(**fields)


async def test_sync_places_new_databases_safely(db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    result = await sync_from_connector(
        db,
        connector_id=c.id,
        reported=[
            rep("orders", version="16.2", environment="Staging"),  # hint matches -> staging
            rep("billing"),  # no hint -> production (strictest)
            rep("crm", engine="mysql", environment="does-not-exist"),  # unknown -> production
        ],
    )
    placed = {d.local_name: d.environment_id for d in result.created}
    assert placed == {"orders": w.staging.id, "billing": w.prod.id, "crm": w.prod.id}
    orders = next(d for d in result.created if d.local_name == "orders")
    assert (orders.status, orders.version) == (DatasourceStatus.CONNECTED, "16.2")
    discovered = await db.scalars(
        select(AuditLog.action).where(AuditLog.action == "datasource.discovered")
    )
    assert len(list(discovered)) == 3


async def test_sync_updates_and_marks_missing(db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    await sync_from_connector(db, connector_id=c.id, reported=[rep("a"), rep("b")])
    second = await sync_from_connector(
        db,
        connector_id=c.id,
        reported=[rep("a", reachable=False, version="17.0"), rep("a")],  # duplicate ignored
    )
    assert second.created == []
    assert [d.local_name for d in second.updated] == ["a"]
    a = second.updated[0]
    assert (a.status, a.version) == (DatasourceStatus.ERROR, "17.0")
    assert [d.local_name for d in second.missing] == ["b"]
    assert second.missing[0].status == DatasourceStatus.UNKNOWN


async def test_sync_keeps_user_chosen_environment(db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    first = await sync_from_connector(db, connector_id=c.id, reported=[rep("orders")])
    ds = first.created[0]
    ds.environment_id = w.staging.id  # a user moved it
    await db.flush()
    await sync_from_connector(
        db, connector_id=c.id, reported=[rep("orders", environment="production")]
    )
    assert ds.environment_id == w.staging.id


async def test_revoked_connector_cannot_sync(db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    c.status = ConnectorStatus.REVOKED
    await db.flush()
    with pytest.raises(ConnectorRevokedError):
        await sync_from_connector(db, connector_id=c.id, reported=[rep("x")])


def test_reported_engine_list_matches_db_engines() -> None:
    allowed = set(typing.get_args(ReportedDatasource.model_fields["engine"].annotation))
    assert allowed == {e.value for e in DbEngine}


def test_reported_name_is_validated() -> None:
    with pytest.raises(ValueError, match="letters"):
        rep("bad name; DROP TABLE")


# ---- catalog: the databases on each server ---------------------------------------------------

CATALOG = {
    "databases": [
        {"name": "zipzy_hrm", "size_bytes": 5_000_000, "tables": 42},
        {"name": "payments", "size_bytes": 1_000_000, "tables": 7},
        {"name": "empty_one", "size_bytes": None, "tables": None},
    ],
    "truncated": False,
}


async def test_sync_stores_the_catalog_and_api_shows_it(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    viewer, _ = await member(db, w.t, R.VIEWER)
    result = await sync_from_connector(
        db, connector_id=c.id, reported=[rep("main", engine="mysql", catalog=CATALOG)]
    )
    ds = result.created[0]

    r = await api.get(url(w.t, f"/{ds.id}"), headers=hdr(viewer))
    assert r.status_code == 200
    summary = r.json()["catalog"]
    assert summary["database_count"] == 3
    assert summary["total_size_bytes"] == 6_000_000
    assert summary["truncated"] is False and summary["updated_at"]

    r = await api.get(url(w.t, f"/{ds.id}/databases"), headers=hdr(viewer))
    assert r.status_code == 200
    body = r.json()
    assert body["datasource_id"] == str(ds.id) and body["updated_at"]
    assert body["databases"][0] == {"name": "zipzy_hrm", "size_bytes": 5_000_000, "tables": 42}
    assert [d["name"] for d in body["databases"]] == ["zipzy_hrm", "payments", "empty_one"]


async def test_unreachable_server_keeps_the_last_catalog(db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    first = await sync_from_connector(db, connector_id=c.id, reported=[rep("a", catalog=CATALOG)])
    ds = first.created[0]
    seen_at = ds.catalog_updated_at
    await sync_from_connector(db, connector_id=c.id, reported=[rep("a", reachable=False)])
    assert ds.status == DatasourceStatus.ERROR
    assert ds.catalog == CATALOG and ds.catalog_updated_at == seen_at


async def test_old_connector_without_catalog(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    c = await enrolled_connector(db, w.t, w.owner)
    first = await sync_from_connector(db, connector_id=c.id, reported=[rep("old")])
    ds = first.created[0]
    r = await api.get(url(w.t, f"/{ds.id}"), headers=hdr(w.owner))
    assert r.json()["catalog"] is None
    r = await api.get(url(w.t, f"/{ds.id}/databases"), headers=hdr(w.owner))
    assert r.json() == {
        "datasource_id": str(ds.id),
        "updated_at": None,
        "truncated": False,
        "databases": [],
    }


async def test_catalog_follows_environment_visibility(api: AsyncClient, db: AsyncSession) -> None:
    w = await world(db)
    other = await world(db)
    blind = await make_custom_role(db, w.t, "no-access", set())
    contractor, m = await member(db, w.t, R.BACKEND_DEV)
    await override_role(db, m, w.prod, blind.id)  # cannot see production
    path = f"/{w.pg_prod.id}/databases"
    assert (await api.get(url(w.t, path), headers=hdr(contractor))).status_code == 404
    assert (await api.get(url(w.t, path), headers=hdr(other.owner))).status_code == 404


def test_reported_catalog_is_bounded() -> None:
    too_many = {"databases": [{"name": f"d{i}"} for i in range(1001)]}
    with pytest.raises(ValueError, match="1000"):
        rep("x", catalog=too_many)
    with pytest.raises(ValueError):
        rep("x", catalog={"databases": [{"name": "d", "size_bytes": -1}]})
