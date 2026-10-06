"""Reading the audit log ("who did what, when").

Newest first. Filters can be combined. Pagination is keyset on (created_at, id), which uses
the (tenant_id, created_at) index, so page 1000 is as fast as page 1.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Connector, User
from app.models.enums import ActorType


@dataclass(slots=True)
class AuditFilters:
    actor_id: uuid.UUID | None = None
    actor_type: str | None = None
    action: str | None = None  # exact ("member.role_changed") or prefix ("member.")
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(slots=True)
class AuditRow:
    entry: AuditLog
    actor_email: str | None
    actor_name: str | None


async def list_entries(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    filters: AuditFilters,
    limit: int,
    after: tuple[datetime, int] | None,
) -> tuple[list[AuditRow], bool]:
    """Returns up to `limit` rows older than `after`, and whether more rows exist."""
    query = (
        select(AuditLog, User.email, User.full_name, Connector.name)
        .outerjoin(User, and_(AuditLog.actor_type == ActorType.USER, User.id == AuditLog.actor_id))
        .outerjoin(
            Connector,
            and_(
                AuditLog.actor_type == ActorType.CONNECTOR,
                Connector.id == AuditLog.actor_id,
                Connector.tenant_id == tenant_id,
            ),
        )
        .where(AuditLog.tenant_id == tenant_id)
    )
    f = filters
    if f.actor_id is not None:
        query = query.where(AuditLog.actor_id == f.actor_id)
    if f.actor_type is not None:
        query = query.where(AuditLog.actor_type == f.actor_type)
    if f.action is not None:
        if f.action.endswith("."):
            query = query.where(AuditLog.action.startswith(f.action, autoescape=True))
        else:
            query = query.where(AuditLog.action == f.action)
    if f.target_type is not None:
        query = query.where(AuditLog.target_type == f.target_type)
    if f.target_id is not None:
        query = query.where(AuditLog.target_id == f.target_id)
    if f.since is not None:
        query = query.where(AuditLog.created_at >= f.since)
    if f.until is not None:
        query = query.where(AuditLog.created_at < f.until)
    if after is not None:
        at, row_id = after
        query = query.where(
            or_(AuditLog.created_at < at, and_(AuditLog.created_at == at, AuditLog.id < row_id))
        )

    rows = (
        await session.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    return [
        AuditRow(entry=a, actor_email=email, actor_name=full_name or connector_name)
        for a, email, full_name, connector_name in rows[:limit]
    ], has_more
