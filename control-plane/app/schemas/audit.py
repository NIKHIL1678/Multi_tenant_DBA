"""Response shapes for the audit log."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditActorOut(BaseModel):
    type: str  # user | connector | agent | system
    id: uuid.UUID | None
    # Filled in when we still know who it was (users and connectors can be removed later;
    # the audit row is kept forever, so these may be None for old entries).
    email: str | None
    name: str | None


class AuditEntryOut(BaseModel):
    id: int
    created_at: datetime
    actor: AuditActorOut
    action: str  # e.g. "member.role_changed"
    target_type: str | None
    target_id: uuid.UUID | None
    details: dict[str, Any] | None
    ip_address: str | None
    request_id: str | None
