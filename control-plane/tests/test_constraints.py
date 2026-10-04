"""Database-level guarantees that must hold even if application code has a bug."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role
from tests.factories import make_tenant, make_user


async def test_check_constraint_rejects_unknown_status(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, status) "
                    "VALUES (:id, 'x', :slug, 'free', 'hacked')"
                ),
                {"id": uuid.uuid4(), "slug": f"s-{uuid.uuid4().hex[:12]}"},
            )


async def test_system_role_keys_are_unique(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(Role(tenant_id=None, key="dba", name="Duplicate DBA", is_system=True))
            await db.flush()


async def test_custom_role_key_may_repeat_across_tenants(db: AsyncSession) -> None:
    t_a, t_b = await make_tenant(db), await make_tenant(db)
    db.add_all(
        [
            Role(tenant_id=t_a.id, key="auditor", name="Auditor"),
            Role(tenant_id=t_b.id, key="auditor", name="Auditor"),
        ]
    )
    await db.flush()


async def test_custom_role_key_unique_within_tenant(db: AsyncSession) -> None:
    t = await make_tenant(db)
    db.add(Role(tenant_id=t.id, key="auditor", name="Auditor"))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(Role(tenant_id=t.id, key="auditor", name="Auditor 2"))
            await db.flush()


async def test_email_is_case_insensitive_unique(db: AsyncSession) -> None:
    u = await make_user(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await make_user(db, email=u.email.upper())