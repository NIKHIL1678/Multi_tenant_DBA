from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PermissionRow, Role, RolePermission
from app.rbac.catalog import (
    PERMISSION_DESCRIPTIONS,
    SYSTEM_ROLE_NAMES,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    system_role_id,
)
from tests.conftest import alembic_config


def test_migrations_roundtrip() -> None:
    """Every migration must downgrade cleanly and re-apply."""
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_models_match_migrations() -> None:
    """Fails if a model changed without a migration (alembic autogenerate diff is empty)."""
    command.check(alembic_config())


async def test_seed_permissions_match_catalog(db: AsyncSession) -> None:
    rows = {r.key: r.description for r in (await db.scalars(select(PermissionRow))).all()}
    assert rows == {str(p): d for p, d in PERMISSION_DESCRIPTIONS.items()}
    assert set(rows) == {str(p) for p in Permission}


async def test_seed_system_roles_match_catalog(db: AsyncSession) -> None:
    roles = (await db.scalars(select(Role).where(Role.is_system.is_(True)))).all()
    assert {r.key: (r.id, r.name, r.tenant_id) for r in roles} == {
        role.value: (system_role_id(role), name, None) for role, name in SYSTEM_ROLE_NAMES.items()
    }
    for role, expected in SYSTEM_ROLE_PERMISSIONS.items():
        got = set(
            (
                await db.scalars(
                    select(RolePermission.permission_key).where(
                        RolePermission.role_id == system_role_id(role)
                    )
                )
            ).all()
        )
        assert got == {str(p) for p in expected}, role