"""snapshots

What each collector (health, table_stats, indexes) found on a datasource, one row per run, so
pages can show the latest and trends can be drawn later. Statistics and metadata only, never
table rows. Rows go with their datasource (ON DELETE CASCADE).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 10:14:08.714906
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("datasource_id", sa.UUID(), nullable=False),
        sa.Column("collector", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "collector IN ('health', 'table_stats', 'indexes')", name=op.f("ck_snapshots_collector")
        ),
        sa.ForeignKeyConstraint(
            ["datasource_id"],
            ["datasources.id"],
            name=op.f("fk_snapshots_datasource_id_datasources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_snapshots_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    op.create_index(
        op.f("ix_snapshots_datasource_id_collector_collected_at"),
        "snapshots",
        ["datasource_id", "collector", "collected_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_snapshots_datasource_id_collector_collected_at"), table_name="snapshots")
    op.drop_table("snapshots")
