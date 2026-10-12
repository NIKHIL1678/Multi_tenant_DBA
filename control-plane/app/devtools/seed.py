"""Sample data for local development:  python -m app.devtools.seed

Creates two demo companies, their environments, and one user per role, plus a freelance
DBA who belongs to both companies. Every demo user's password is DEMO_PASSWORD.
Each company also gets a "demo connector" that reports sample databases, so the dashboard
has something to show before a real connector exists (Phase 4).
Safe to run more than once. Refuses outside development.
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.models import (
    Connector,
    Environment,
    MemberEnvironmentRole,
    Tenant,
    TenantMember,
    User,
)
from app.models.enums import AuthProvider, ConnectorStatus, TenantPlan
from app.rbac.catalog import SystemRole, system_role_id
from app.schemas.datasources import ReportedCatalog, ReportedDatabase, ReportedDatasource
from app.services.datasources import sync_from_connector

R = SystemRole
DEMO_PASSWORD = "zipzy-demo-pass"  # noqa: S105 - local demo data only

# slug: (name, plan, [(email, full name, role, {env: override role})])
COMPANIES: dict[str, tuple[str, TenantPlan, list[tuple[str, str, SystemRole, dict[str, R]]]]] = {
    "sharma-textiles": (
        "Sharma Textiles",
        TenantPlan.GROWTH,
        [
            ("owner@sharma.test", "Anil Sharma", R.OWNER, {}),
            ("dba@sharma.test", "Priya Verma", R.DBA, {}),
            ("it@sharma.test", "Vikram Singh", R.IT_ADMIN, {}),
            ("dev@sharma.test", "Rahul Gupta", R.BACKEND_DEV, {"production": R.VIEWER}),
            ("viewer@sharma.test", "Neha Jain", R.VIEWER, {}),
            ("freelance.dba@example.test", "Arjun Mehta", R.DBA, {}),
        ],
    ),
    "gupta-foods": (
        "Gupta Foods",
        TenantPlan.STARTER,
        [
            ("owner@gupta.test", "Sunita Gupta", R.OWNER, {}),
            ("freelance.dba@example.test", "Arjun Mehta", R.VIEWER, {}),
        ],
    ),
}
ENVIRONMENTS = [("production", True), ("staging", False), ("development", False)]

DEMO_CONNECTOR = "Demo connector (sample data)"
# slug: [(local name, engine, version, reachable, environment)]
DEMO_DATABASES: dict[str, list[tuple[str, str, str, bool, str]]] = {
    "sharma-textiles": [
        ("orders-db", "postgres", "16.4", True, "production"),
        ("inventory", "mysql", "8.0.39", True, "production"),
        ("analytics", "mongodb", "7.0.12", False, "production"),
        ("orders-db-staging", "postgres", "16.4", True, "staging"),
        ("payroll", "mssql", "2022 CU14", True, "staging"),
        ("website-dev", "mariadb", "11.4.3", True, "development"),
    ],
    "gupta-foods": [
        ("billing", "postgres", "15.8", True, "production"),
    ],
}

MB = 1024 * 1024
# What the demo servers hold (name, size, tables), as a 0.3+ connector would report it.
DEMO_CATALOGS: dict[str, list[tuple[str, int, int | None]]] = {
    "orders-db": [("orders", 18_400 * MB, 64), ("postgres", 8 * MB, None)],
    "inventory": [
        ("inventory", 6_200 * MB, 38),
        ("warehouse_sync", 1_150 * MB, 12),
        ("audit_archive", 940 * MB, 4),
    ],
    "orders-db-staging": [("orders", 2_100 * MB, 64)],
    "website-dev": [("wordpress", 320 * MB, 41), ("analytics_dev", 75 * MB, 9)],
    "billing": [("billing", 4_700 * MB, 27), ("postgres", 8 * MB, None)],
}


def _demo_catalog(name: str) -> ReportedCatalog | None:
    entries = DEMO_CATALOGS.get(name)
    if entries is None:
        return None
    return ReportedCatalog(
        databases=[
            ReportedDatabase(name=db, size_bytes=size, tables=tables)
            for db, size, tables in entries
        ]
    )


async def _user(session: AsyncSession, email: str, name: str) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=name,
            auth_provider=AuthProvider.PASSWORD,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        session.add(user)
        await session.flush()
    return user


async def seed(session: AsyncSession) -> list[str]:
    created: list[str] = []
    for slug, (name, plan, people) in COMPANIES.items():
        if await session.scalar(select(Tenant).where(Tenant.slug == slug)):
            continue
        tenant = Tenant(name=name, slug=slug, plan=plan)
        session.add(tenant)
        await session.flush()

        envs: dict[str, Environment] = {}
        for env_name, is_prod in ENVIRONMENTS:
            env = Environment(tenant_id=tenant.id, name=env_name, is_production=is_prod)
            session.add(env)
            envs[env_name] = env
        await session.flush()

        for email, full_name, role, overrides in people:
            user = await _user(session, email, full_name)
            member = TenantMember(
                tenant_id=tenant.id, user_id=user.id, role_id=system_role_id(role)
            )
            session.add(member)
            await session.flush()
            for env_name, env_role in overrides.items():
                session.add(
                    MemberEnvironmentRole(
                        member_id=member.id,
                        environment_id=envs[env_name].id,
                        role_id=system_role_id(env_role),
                    )
                )
        created.append(name)
    await session.commit()
    return created


async def seed_demo_databases(session: AsyncSession) -> list[str]:
    """Give each demo company a demo connector that reports sample databases.

    Goes through the same code path a real connector report uses (sync_from_connector), so
    environments, audit entries and statuses come out exactly as they will in production.
    """
    added: list[str] = []
    for slug, databases in DEMO_DATABASES.items():
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            continue
        exists = await session.scalar(
            select(Connector.id).where(
                Connector.tenant_id == tenant.id, Connector.name == DEMO_CONNECTOR
            )
        )
        if exists is not None:
            continue
        owner_id = await session.scalar(
            select(TenantMember.user_id)
            .where(
                TenantMember.tenant_id == tenant.id,
                TenantMember.role_id == system_role_id(R.OWNER),
            )
            .limit(1)
        )
        if owner_id is None:
            continue
        connector = Connector(
            tenant_id=tenant.id,
            name=DEMO_CONNECTOR,
            status=ConnectorStatus.OFFLINE,  # enrolled, never online: there is no program
            version="0.1.0-demo",
            created_by=owner_id,
        )
        session.add(connector)
        await session.flush()
        await sync_from_connector(
            session,
            connector_id=connector.id,
            reported=[
                ReportedDatasource(
                    local_name=name,
                    engine=engine,
                    version=version,
                    reachable=reachable,
                    environment=environment,
                    catalog=_demo_catalog(name) if reachable else None,
                )
                for name, engine, version, reachable, environment in databases
            ],
        )
        added.append(tenant.name)
    await session.commit()
    return added


async def main() -> int:
    if get_settings().app_env != "development":
        print("Refusing to seed: APP_ENV is not 'development'.")
        return 1
    async with get_sessionmaker()() as session:
        created = await seed(session)
        with_databases = await seed_demo_databases(session)
    await get_engine().dispose()
    print(f"Seeded: {', '.join(created)}" if created else "Companies: demo data already exists.")
    if with_databases:
        print(f"Sample databases added for: {', '.join(with_databases)}")
    print(f"Sign in as any demo user (e.g. dba@sharma.test) with password: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
