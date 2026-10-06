"""password auth and sessions

This product has its own sign-in: password hashes on users, one auth_sessions row per
signed-in device (refresh token hash), and `zipzy_accounts` removed as a sign-in type.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04 03:30:33.629585
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.UUID(), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_auth_sessions_refresh_token_hash")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))

    # Sign-in types: password | google (zipzy_accounts no longer used).
    op.execute("UPDATE users SET auth_provider = 'password' WHERE auth_provider = 'zipzy_accounts'")
    op.drop_constraint(op.f("ck_users_auth_provider"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_auth_provider"), "users", "auth_provider IN ('password', 'google')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_auth_provider"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_auth_provider"),
        "users",
        "auth_provider IN ('zipzy_accounts', 'google', 'password')",
    )
    op.drop_column("users", "password_hash")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")