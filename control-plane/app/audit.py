"""Audit trail writer.

Call `record_audit` inside the same transaction as the change it describes:
if the change is rolled back, so is its audit row (no "ghost" history).

Action names are "<thing>.<verb>", e.g. "tenant.created", "member.role_changed".
Never put secrets, tokens or customer row data in `details`.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.models import AuditLog
from app.models.enums import ActorType


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request is not None and request.client else None


async def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_id: uuid.UUID | None,
    actor_type: ActorType = ActorType.USER,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    row = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=client_ip(request),
        request_id=request_id_var.get(),
    )
    session.add(row)
    await session.flush()
    return row
