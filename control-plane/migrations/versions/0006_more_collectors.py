"""more collectors

Snapshots may now also hold slow_queries (normalized statement statistics), locks (lock waits
and long transactions) and table_index (every table's name, rows and size). Statistics and
metadata only, never table rows.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "collector IN ('health', 'table_stats', 'indexes')"
NEW = (
    "collector IN ('health', 'table_stats', 'indexes', 'slow_queries', 'locks', 'table_index')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_snapshots_collector"), "snapshots", type_="check")
    op.create_check_constraint(op.f("ck_snapshots_collector"), "snapshots", NEW)


def downgrade() -> None:
    op.execute("DELETE FROM snapshots WHERE collector IN ('slow_queries', 'locks', 'table_index')")
    op.drop_constraint(op.f("ck_snapshots_collector"), "snapshots", type_="check")
    op.create_check_constraint(op.f("ck_snapshots_collector"), "snapshots", OLD)
