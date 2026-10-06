"""Request and response shapes for members and roles."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class RoleOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    is_system: bool
    permissions: list[str]


class RoleRef(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class EnvironmentRoleOut(BaseModel):
    environment_id: uuid.UUID
    environment_name: str
    role: RoleRef


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: RoleRef
    status: str
    joined_at: datetime
    environment_roles: list[EnvironmentRoleOut]


class MemberUpdateIn(BaseModel):
    role_id: uuid.UUID | None = None
    status: Literal["active", "suspended"] | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "MemberUpdateIn":
        if self.role_id is None and self.status is None:
            raise ValueError("Send role_id and/or status")
        return self


class EnvironmentRoleIn(BaseModel):
    role_id: uuid.UUID
