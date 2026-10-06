"""Sample data for local development:  python -m app.devtools.seed

Creates two demo companies, their environments, and one user per role, plus a freelance
DBA who belongs to both companies. Every demo user's password is DEMO_PASSWORD.
Safe to run more than once. Refuses outside development.
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.models import Environment, MemberEnvironmentRole, Tenant, TenantMember, User
from app.models.enums import AuthProvider, TenantPlan
from app.rbac.catalog import SystemRole, system_role_id

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


async def main() -> int:
    if get_settings().app_env != "development":
        print("Refusing to seed: APP_ENV is not 'development'.")
        return 1
    async with get_sessionmaker()() as session:
        created = await seed(session)
    await get_engine().dispose()
    print(
        f"Seeded: {', '.join(created)}" if created else "Nothing to do: demo data already exists."
    )
    print(f"Sign in as any demo user (e.g. dba@sharma.test) with password: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
