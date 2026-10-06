"""Response shapes for the current user. These become the dashboard's TypeScript types."""

import uuid

from pydantic import BaseModel


class MembershipOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    role_key: str
    role_name: str


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    memberships: list[MembershipOut]


class DevUserOut(BaseModel):
    email: str
    full_name: str | None
