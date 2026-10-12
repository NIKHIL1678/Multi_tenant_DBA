from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.devtools.seed import DEMO_DATABASES, seed, seed_demo_databases
from app.models import Datasource, Environment, Tenant, TenantMember, User
from app.rbac.catalog import Permission
from app.rbac.service import resolve_access


async def test_seed_is_idempotent_and_wires_roles(db: AsyncSession) -> None:
    assert set(await seed(db)) == {"Sharma Textiles", "Gupta Foods"}
    assert await seed(db) == []

    freelancer = await db.scalar(select(User).where(User.email == "freelance.dba@example.test"))
    assert freelancer is not None
    memberships = await db.scalar(
        select(func.count()).select_from(TenantMember).where(TenantMember.user_id == freelancer.id)
    )
    assert memberships == 2

    sharma = await db.scalar(select(Tenant).where(Tenant.slug == "sharma-textiles"))
    dev = await db.scalar(select(User).where(User.email == "dev@sharma.test"))
    assert sharma is not None and dev is not None
    prod = await db.scalar(
        select(Environment).where(
            Environment.tenant_id == sharma.id, Environment.name == "production"
        )
    )
    assert prod is not None
    in_prod = await resolve_access(db, user_id=dev.id, tenant_id=sharma.id, environment_id=prod.id)
    anywhere = await resolve_access(db, user_id=dev.id, tenant_id=sharma.id)
    assert in_prod is not None and not in_prod.has(Permission.DATA_READ)
    assert anywhere is not None and anywhere.has(Permission.DATA_READ)


async def test_demo_databases_land_in_their_environments_once(db: AsyncSession) -> None:
    await seed(db)
    assert set(await seed_demo_databases(db)) == {"Sharma Textiles", "Gupta Foods"}
    assert await seed_demo_databases(db) == []

    sharma = await db.scalar(select(Tenant).where(Tenant.slug == "sharma-textiles"))
    assert sharma is not None
    rows = (
        await db.execute(
            select(Datasource.local_name, Environment.name, Datasource.status)
            .join(Environment, Environment.id == Datasource.environment_id)
            .where(Datasource.tenant_id == sharma.id)
        )
    ).all()
    assert len(rows) == len(DEMO_DATABASES["sharma-textiles"])
    placed = {name: (env, status) for name, env, status in rows}
    assert placed["payroll"] == ("staging", "connected")
    assert placed["analytics"] == ("production", "error")


async def test_demo_servers_list_their_databases(db: AsyncSession) -> None:
    await seed(db)
    await seed_demo_databases(db)
    rows = (await db.execute(select(Datasource.local_name, Datasource.catalog))).all()
    catalogs = {name: catalog for name, catalog in rows}
    inventory = catalogs["inventory"]
    assert inventory is not None
    assert [d["name"] for d in inventory["databases"]] == [
        "inventory",
        "warehouse_sync",
        "audit_archive",
    ]
    assert catalogs["analytics"] is None, "an unreachable server has no catalog"
