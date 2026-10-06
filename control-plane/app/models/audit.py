"""Audit log."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, enum_check
from app.models.enums import ActorType


class AuditLog(Base):
    """Append-only record of everything.

    No foreign keys on purpose: audit rows must outlive the rows they describe.
    Never store secrets or customer row data in `details`.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "actor_id", "created_at"),
        Index(None, "target_type", "target_id"),
        enum_check("actor_type", ActorType),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
