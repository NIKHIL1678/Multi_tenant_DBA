"""Request and response shapes for companies (tenants)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,48}[a-z0-9])$")
RESERVED_SLUGS = frozenset({"admin", "api", "app", "www", "help", "support", "status", "zipzy"})


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Name cannot be blank")
    return v


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    # Optional; generated from the name when missing. Used in URLs, so it is strict.
    slug: str | None = Field(default=None, min_length=3, max_length=50)

    _name = field_validator("name")(_clean_name)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not SLUG_RE.match(v) or "--" in v:
            raise ValueError("Use 3-50 lowercase letters, digits and single hyphens")
        if v in RESERVED_SLUGS:
            raise ValueError("This name is reserved")
        return v


class TenantUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)

    _name = field_validator("name")(_clean_name)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str
    created_at: datetime
    my_role_key: str
    my_permissions: list[str]


class TenantOverviewOut(BaseModel):
    tenant_id: uuid.UUID
    environments: int
    members: int
    connectors_by_status: dict[str, int]
    datasources_by_engine: dict[str, int]
