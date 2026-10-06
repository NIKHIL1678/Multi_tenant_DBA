"""Request and response shapes for invitations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.members import RoleRef


class InvitationCreateIn(BaseModel):
    email: EmailStr
    role_id: uuid.UUID


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: RoleRef
    invited_by_email: str | None
    expires_at: datetime
    created_at: datetime


class InvitationCreatedOut(InvitationOut):
    # Shown ONCE. The dashboard turns it into a link: <dashboard>/invite#<token>.
    # Only its hash is stored, so it cannot be shown again; re-invite to get a new one.
    token: str


class InvitationTokenIn(BaseModel):
    # Sent in the body (never in the URL) so it does not end up in access logs.
    token: str = Field(min_length=20, max_length=200)


class InvitationPreviewOut(BaseModel):
    tenant_name: str
    role_name: str
    email: str
    invited_by_name: str | None
    expires_at: datetime


class InvitationAcceptedOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role_key: str
