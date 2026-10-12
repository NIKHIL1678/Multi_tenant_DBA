"""datasource catalog

The databases on each customer server (MySQL schemas / Postgres databases), as the connector
last reported them: names, sizes and table counts. Never rows.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 09:40:26.378175
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasources",
        sa.Column("catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "datasources",
        sa.Column("catalog_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("datasources", "catalog_updated_at")
    op.drop_column("datasources", "catalog")
