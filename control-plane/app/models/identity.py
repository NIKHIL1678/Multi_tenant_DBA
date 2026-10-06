"""Tenants, users, memberships, invitations."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import CITEXT, INET, UUID

from app.models.base import (
    TIMESTAMPTZ,
    Base,
    created_at_col,
    enum_check,
    updated_at_col,
    uuid_pk,
)
from app.models.enums import AuthProvider, MemberStatus, TenantPlan, TenantStatus, UserStatus


class Tenant(Base):
    """A customer company."""

    __tablename__ = "tenants"
    __table_args__ = (
        enum_check("plan", TenantPlan),
        enum_check("status", TenantStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default=TenantPlan.FREE)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=TenantStatus.ACTIVE)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class User(Base):
    """A person. Global: one user can be a member of many tenants."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "external_id"),
        enum_check("auth_provider", AuthProvider),
        enum_check("status", UserStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(150))
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    # Argon2id hash; NULL for users who sign in with an external provider.
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=UserStatus.ACTIVE)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class TenantMember(Base):
    """A user's membership in a tenant, with a tenant-wide role."""

    __tablename__ = "tenant_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        Index(None, "user_id"),
        enum_check("status", MemberStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default=MemberStatus.ACTIVE)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    joined_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Invitation(Base):
    """Pending invite to join a tenant. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "invitations"
    __table_args__ = (Index(None, "tenant_id", "email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = created_at_col()
    


class AuthSession(Base):
    """One signed-in device. Stores only the hash of its refresh token.

    Revoking the row signs that device out.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (Index(None, "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    # Set when this session was rotated; the token it was replaced by.
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at_col()
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)    