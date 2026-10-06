"""Audit log viewer.

GET /v1/tenants/{tenant_id}/audit-log      needs audit.read (Owner, DBA, IT Admin)

Query parameters (all optional, combinable):
    actor_id, actor_type, action ("member.role_changed" exact, or "member." for all member.*),
    target_type, target_id, since, until (ISO 8601), limit (1-200, default 50), cursor
Response: {"items": [...newest first...], "next_cursor": "..." | null}
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from app.auth.current_user import DbSession
from app.auth.permissions import require
from app.models.enums import ActorType
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext
from app.schemas.audit import AuditActorOut, AuditEntryOut
from app.services.audit_log import AuditFilters, AuditRow, list_entries

router = APIRouter(prefix="/v1/tenants/{tenant_id}/audit-log", tags=["audit"])

CanReadAudit = Annotated[AccessContext, Depends(require(Permission.AUDIT_READ))]


def _out(row: AuditRow) -> AuditEntryOut:
    a = row.entry
    return AuditEntryOut(
        id=a.id,
        created_at=a.created_at,
        actor=AuditActorOut(
            type=a.actor_type, id=a.actor_id, email=row.actor_email, name=row.actor_name
        ),
        action=a.action,
        target_type=a.target_type,
        target_id=a.target_id,
        details=a.details,
        ip_address=str(a.ip_address) if a.ip_address is not None else None,
        request_id=a.request_id,
    )


@router.get("")
async def list_audit_log(
    tenant_id: uuid.UUID,
    _: CanReadAudit,
    session: DbSession,
    actor_id: uuid.UUID | None = None,
    actor_type: ActorType | None = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    target_type: Annotated[str | None, Query(max_length=50)] = None,
    target_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[AuditEntryOut]:
    rows, has_more = await list_entries(
        session,
        tenant_id=tenant_id,
        filters=AuditFilters(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            since=since,
            until=until,
        ),
        limit=limit,
        after=decode_cursor(cursor) if cursor else None,
    )
    next_cursor = (
        encode_cursor(rows[-1].entry.created_at, rows[-1].entry.id) if has_more and rows else None
    )
    return Page[AuditEntryOut](items=[_out(r) for r in rows], next_cursor=next_cursor)
