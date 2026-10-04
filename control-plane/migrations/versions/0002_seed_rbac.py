"""seed permissions and system roles

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03

Data is frozen here on purpose: migrations must not import application code that can
change later. tests/test_migrations.py checks this seed still matches app/rbac/catalog.py.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS: list[tuple[str, str]] = [
    ("org.manage", "Manage tenant settings, billing and deletion"),
    ("members.manage", "Invite and remove members, change roles"),
    ("connectors.manage", "Create and revoke connectors, issue enrollment tokens"),
    ("datasources.manage", "Add and remove datasources, assign environments"),
    ("metadata.read", "View health, schema, indexes and statistics (no row data)"),
    ("data.read", "Run read queries that return row data"),
    ("findings.read", "View agent findings and recommendations"),
    ("actions.request", "Propose a change to a datasource"),
    ("actions.approve", "Approve a proposed change"),
    ("actions.execute", "Execute an approved change"),
    ("audit.read", "View the audit log"),
]

ALL = [k for k, _ in PERMISSIONS]

# (id, key, name, permissions)
ROLES: list[tuple[str, str, str, list[str]]] = [
    ("6b96a494-5e3b-5855-82b7-d97b4432ecf6", "owner", "Owner", ALL),
    (
        "dfeb9e30-9157-5eba-8537-7caf9382064d",
        "dba",
        "DBA",
        [
            "connectors.manage",
            "datasources.manage",
            "metadata.read",
            "data.read",
            "findings.read",
            "actions.request",
            "actions.approve",
            "actions.execute",
            "audit.read",
        ],
    ),
    (
        "964c26bd-6a02-5434-b8ab-74eeda7e8842",
        "it_admin",
        "IT Admin",
        [
            "members.manage",
            "connectors.manage",
            "datasources.manage",
            "metadata.read",
            "findings.read",
            "audit.read",
        ],
    ),
    (
        "5cab5b4e-2fb1-5d2c-91c2-a992bf5016e1",
        "backend_dev",
        "Backend Developer",
        ["metadata.read", "data.read", "findings.read", "actions.request"],
    ),
    (
        "ec74b942-4b92-509c-98b4-fbfd60451fdf",
        "viewer",
        "Viewer",
        ["metadata.read", "findings.read"],
    ),
]

permissions_t = sa.table(
    "permissions", sa.column("key", sa.String), sa.column("description", sa.String)
)
roles_t = sa.table(
    "roles",
    sa.column("id", sa.Uuid),
    sa.column("tenant_id", sa.Uuid),
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("is_system", sa.Boolean),
)
role_permissions_t = sa.table(
    "role_permissions", sa.column("role_id", sa.Uuid), sa.column("permission_key", sa.String)
)


def upgrade() -> None:
    op.bulk_insert(permissions_t, [{"key": k, "description": d} for k, d in PERMISSIONS])
    op.bulk_insert(
        roles_t,
        [
            {"id": uuid.UUID(rid), "tenant_id": None, "key": key, "name": name, "is_system": True}
            for rid, key, name, _ in ROLES
        ],
    )
    op.bulk_insert(
        role_permissions_t,
        [
            {"role_id": uuid.UUID(rid), "permission_key": p}
            for rid, _, _, perms in ROLES
            for p in perms
        ],
    )


def downgrade() -> None:
    role_ids = [uuid.UUID(rid) for rid, *_ in ROLES]
    op.execute(role_permissions_t.delete().where(role_permissions_t.c.role_id.in_(role_ids)))
    op.execute(roles_t.delete().where(roles_t.c.id.in_(role_ids)))
    op.execute(permissions_t.delete().where(permissions_t.c.key.in_(ALL)))